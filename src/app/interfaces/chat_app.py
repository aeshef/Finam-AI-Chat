#!/usr/bin/env python3
"""
Streamlit веб-интерфейс для AI ассистента трейдера

Использование:
    poetry run streamlit run src/app/chat_app.py
    streamlit run src/app/chat_app.py
"""

import json
import os
import sys

import streamlit as st
try:
    from prometheus_client import start_http_server
except Exception:  # pragma: no cover
    start_http_server = None  # type: ignore
import yaml
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Ensure project root is on sys.path so `src` can be imported when run via Streamlit
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.app.adapters import FinamAPIClient
from src.app.core import call_llm, get_settings
from src.app.core.parsing import extract_api_request as shared_extract_api_request
from src.app.orchestration.router import ToolRouter, ToolRequest
from src.app.orchestration.graph import execute_graph
from src.app.orchestration.types import OrchestrationContext
from src.app.core.audit import get_audit_logger
from src.app.alerts.engine import build_default_engine
from src.app.portfolio.aggregate import get_portfolio_snapshot, build_sunburst_data
from src.app.portfolio.equity import compute_equity_curve
from src.app.backtest.ui import store_backtest_result, render_backtest_export
from src.app.scanner.dsl import ScreenSpec, FilterSpec, SortSpec, run_screen
from src.app.core.normalize import normalize_iso8601
import re as _re


def create_system_prompt() -> str:
    """Создать системный промпт для AI ассистента"""
    return """Ты - AI ассистент трейдера, работающий с Finam TradeAPI.

Когда пользователь задает вопрос о рынке, портфеле или хочет совершить действие:
1. Определи нужный API endpoint
2. Укажи запрос в формате: API_REQUEST: METHOD /path
3. После получения данных - проанализируй их и дай понятный ответ

Доступные endpoints:
- GET /v1/instruments/{symbol}/quotes/latest - котировка
- GET /v1/instruments/{symbol}/orderbook - стакан
- GET /v1/instruments/{symbol}/bars - свечи
- GET /v1/accounts/{account_id} - счет и позиции
- GET /v1/accounts/{account_id}/orders - ордера
- POST /v1/accounts/{account_id}/orders - создать ордер
- DELETE /v1/accounts/{account_id}/orders/{order_id} - отменить ордер

Отвечай на русском, кратко и по делу."""


def extract_api_request(text: str) -> tuple[str | None, str | None]:
    # Delegate to shared util for consistency
    method, path = shared_extract_api_request(text)
    return method, path


def main() -> None:  # noqa: C901
    """Главная функция Streamlit приложения"""
    st.set_page_config(page_title="AI Трейдер (Finam)", page_icon="🤖", layout="wide")
    # Start Prometheus exporter once
    try:
        if start_http_server and not st.session_state.get("_metrics_exporter_started"):
            port = int(os.getenv("METRICS_PORT", "8000"))
            start_http_server(port)
            st.session_state["_metrics_exporter_started"] = True
    except Exception:
        pass

    # Заголовок
    st.title("🤖 AI Ассистент Трейдера")
    st.caption("Интеллектуальный помощник для работы с Finam TradeAPI")

    # Sidebar с настройками
    with st.sidebar:
        st.header("⚙️ Настройки")
        settings = get_settings()
        st.info(f"**Модель:** {settings.openrouter_model}")

        # Backend настройки
        with st.expander("🔑 Finam API", expanded=False):
            api_token = st.text_input(
                "Access Token",
                type="password",
                help="Токен доступа к Finam TradeAPI (или используйте FINAM_ACCESS_TOKEN)",
            )
            # Fallback: загрузим из auth.json, если поле пустое и нет FINAM_ACCESS_TOKEN
            if not api_token and not os.getenv("FINAM_ACCESS_TOKEN"):
                try:
                    with open(os.path.join(PROJECT_ROOT, "auth.json"), encoding="utf-8") as _af:
                        _aj = json.load(_af)
                        _tok = (_aj or {}).get("token", "")
                        if _tok:
                            api_token = _tok
                            st.caption("Token: загружен из auth.json")
                except Exception:
                    pass
            api_base_url = st.text_input("API Base URL", value="https://api.finam.ru", help="Базовый URL API")
        backend = st.selectbox("Backend", options=["http", "mcp"], index=0, help="Способ выполнения запросов")

        confirm_action = st.checkbox("✅ Подтвердить торговые действия (POST/DELETE)", value=False)

        # Автоподстановка account_id + ручное обновление
        account_id = st.session_state.get("_account_id_autofill", "")
        colAcc1, colAcc2 = st.columns([2,1])
        with colAcc1:
            if account_id:
                st.caption(f"ID счета: {account_id}")
            else:
                st.caption("ID счета: — (попробуйте обновить ниже)")
        with colAcc2:
            if st.button("Обновить ID счёта"):
                # Выполним обновление после инициализации finam_client ниже
                st.session_state["_refresh_account"] = True
        benchmark_symbol = st.text_input("Бенчмарк (символ)", value="SBER@MISX", help="Напр.: SBER@MISX, LQDT@MISX, IMOEX@MISX, SBMX@MISX (ETF на IMOEX), TMOS@MISX, FXRL@MISX")
        st.caption("Используется для сравнения с портфелем на графике 'Equity vs Benchmark'")

        if st.button("🔄 Очистить историю"):
            st.session_state.messages = []
            # also clear backtest/scanner transient state
            for _k in [
                "_bt_metrics",
                "_bt_equity_fig",
                "_bt_trades",
                "_backtest_run",
                "_backtest_preset_name",
                "_run_custom_bt",
                "_custom_bt_cfg",
                "_portfolio_run",
            ]:
                st.session_state.pop(_k, None)
            st.rerun()

        st.markdown("---")
        st.subheader("🔔 Алерты")
        alerts_backend = "http"  # фиксируем http для продового сценария
        bot_token_hint = os.getenv("TELEGRAM_BOT_TOKEN", "")
        st.caption(f"Telegram bot token: {'настроен' if bot_token_hint else 'не задан'}")
        colA1, colA2, colA3 = st.columns(3)
        with colA1:
            start_alerts = st.button("▶️ Запустить алерты")
        with colA2:
            stop_alerts = st.button("⏹️ Остановить алерты")
        with colA3:
            show_recent_alerts = st.button("🧾 Последние события")

        if start_alerts:
            st.session_state["_alerts_engine"] = build_default_engine(backend=alerts_backend)
            try:
                cfg = st.session_state["_alerts_engine"].load_config("configs/alerts.yaml")
                st.session_state["_alerts_engine"].start(cfg)
                st.success("Алерты запущены")
            except Exception as e:  # noqa: BLE001
                st.error(f"Не удалось запустить алерты: {e}")
        if stop_alerts and st.session_state.get("_alerts_engine"):
            try:
                st.session_state["_alerts_engine"].stop()
                st.success("Алерты остановлены")
            except Exception:
                pass
        if show_recent_alerts:
            from src.app.core.audit import get_audit_logger as _gal
            with st.expander("🧾 Последние события алертов", expanded=True):
                st.json({"recent": _gal().recent(50)})

        st.caption("Подписка TG: используйте /start в боте; отписка — /stop. Deep‑links в уведомлениях ведут в UI")

        st.markdown("---")
        st.subheader("📊 Портфель")
        run_portfolio_btn = st.button("Сформировать отчет по портфелю")
        st.session_state["_portfolio_run"] = bool(run_portfolio_btn)

        st.markdown("---")
        st.subheader("🧪 Бэктест")
        # Backtest presets
        preset_names: list[str] = []
        try:
            with open("configs/strategies.yaml", encoding="utf-8") as f:
                strat_cfg = yaml.safe_load(f)
                preset_names = [s.get("name", f"preset_{i}") for i, s in enumerate(strat_cfg.get("strategies", []))]
        except Exception:
            strat_cfg = {"strategies": []}
        selected_preset = st.selectbox("Бэктест пресет", options=["<none>"] + preset_names, index=0)
        run_backtest_preset = st.button("Запустить бэктест пресета")
        if run_backtest_preset and (not selected_preset or selected_preset == "<none>"):
            st.warning("Выберите пресет стратегии в списке выше")
            run_backtest_preset = False

        # Trigger actions and persist in session
        st.session_state["_benchmark_symbol"] = benchmark_symbol
        st.session_state["_backtest_preset_name"] = selected_preset if selected_preset != "<none>" else ""
        st.session_state["_backtest_run"] = run_backtest_preset

        # ✏️ Кастомная стратегия (редактор) — в сайдбаре
        with st.expander("✏️ Кастомная стратегия (редактор)", expanded=False):
            cb_name = st.text_input("Имя пресета", value="custom_strategy")
            cb_symbol = st.text_input("Символ", value="SBER@MISX")
            cb_timeframe = st.selectbox(
                "Таймфрейм (бэк-тест)",
                [
                    "TIME_FRAME_M1",
                    "TIME_FRAME_M5",
                    "TIME_FRAME_M15",
                    "TIME_FRAME_M30",
                    "TIME_FRAME_H1",
                    "TIME_FRAME_H4",
                    "TIME_FRAME_D",
                    "TIME_FRAME_W",
                    "TIME_FRAME_MN",
                ],
                index=6,
            )
            cb_start = st.text_input("Начало", value="последние 180 дней")
            cb_end = st.text_input("Окончание", value="сегодня")
            try:
                _ns_cb = normalize_iso8601(cb_start)
                _ne_cb = normalize_iso8601(cb_end)
                st.caption(f"Интерпретация дат: start={_ns_cb}, end={_ne_cb}")
            except Exception:
                pass

            colr1, colr2 = st.columns(2)
            with colr1:
                entry_type = st.selectbox("Entry rule", ["crossover", "threshold"], index=0)
                if entry_type == "crossover":
                    entry_fast = st.number_input("fast (EMA)", value=12, step=1)
                    entry_slow = st.number_input("slow (EMA)", value=26, step=1)
                    entry_params = {"fast": int(entry_fast), "slow": int(entry_slow)}
                else:
                    entry_ref = st.number_input("ref (порог)", value=0.0, step=1.0)
                    entry_params = {"ref": float(entry_ref)}
            with colr2:
                exit_type = st.selectbox("Exit rule", ["threshold"], index=0)
                exit_ref = st.number_input("ref (порог выхода)", value=0.0, step=1.0)
                exit_params = {"ref": float(exit_ref)}

            colb1, colb2 = st.columns(2)
            with colb1:
                run_custom_bt = st.button("▶️ Запустить кастомный бэктест")
            with colb2:
                save_preset = st.button("💾 Сохранить как пресет")

            if run_custom_bt:
                # Отложенный запуск: сохраняем конфиг в состояние; выполнится в главной области после инициализации router
                cfg_dict = {
                    "name": cb_name or f"{cb_symbol}_{cb_timeframe}",
                    "symbol": cb_symbol,
                    "timeframe": cb_timeframe,
                    "start": cb_start,
                    "end": cb_end,
                    "entry": {"type": entry_type, "params": entry_params},
                    "exit": {"type": exit_type, "params": exit_params},
                }
                st.session_state["_custom_bt_cfg"] = cfg_dict
                st.session_state["_run_custom_bt"] = True
                st.info("Запуск бэктеста запланирован. Результаты появятся ниже на странице.")

            if save_preset:
                try:
                    path_yaml = "configs/strategies.yaml"
                    try:
                        with open(path_yaml, encoding="utf-8") as f:
                            y = yaml.safe_load(f) or {}
                    except Exception:
                        y = {}
                    lst = y.get("strategies", [])
                    base_name = (cb_name or "").strip()
                    if not base_name or base_name.lower() == "custom_strategy":
                        auto_name = f"{cb_symbol}_{cb_timeframe}_E{entry_type}-{entry_params}_X{exit_type}-{exit_params}"
                    else:
                        auto_name = base_name
                    upd = {
                        "name": auto_name,
                        "symbol": cb_symbol,
                        "timeframe": cb_timeframe,
                        "start": cb_start,
                        "end": cb_end,
                        "entry": {"type": entry_type, "params": entry_params},
                        "exit": {"type": exit_type, "params": exit_params},
                    }
                    idx = next((i for i, s in enumerate(lst) if s.get("name") == auto_name), None)
                    if idx is None:
                        lst.append(upd)
                    else:
                        lst[idx] = upd
                    y["strategies"] = lst
                    with open(path_yaml, "w", encoding="utf-8") as f:
                        yaml.safe_dump(y, f, allow_unicode=True, sort_keys=False)
                    st.success(f"Сохранено в {path_yaml} как '{auto_name}'")
                except Exception as e:  # noqa: BLE001
                    st.error(f"Не удалось сохранить пресет: {e}")
        st.markdown("---")
        st.subheader("🧮 Сканер")
        scanner_symbols = st.text_input("Символы (через запятую)", value="SBER,GAZP", help="Можно без рынка: SBER, GAZP; автоматически преобразуем в формат API")
        scanner_timeframe = st.selectbox(
            "Таймфрейм",
            options=[
                "TIME_FRAME_M1",
                "TIME_FRAME_M5",
                "TIME_FRAME_M15",
                "TIME_FRAME_M30",
                "TIME_FRAME_H1",
                "TIME_FRAME_H4",
                "TIME_FRAME_D",
                "TIME_FRAME_W",
                "TIME_FRAME_MN",
            ],
            index=6,
            help="Выберите разбиение баров"
        )
        scanner_start = st.text_input("Начало", value="последние 30 дней", help="Поддерживаются NL: 'сегодня', 'вчера', 'последние 30 дней', 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM'")
        scanner_end = st.text_input("Окончание", value="сегодня", help="Поддерживаются NL: 'сегодня', 'вчера', 'последние N дней', ISO8601")
        try:
            _ns = normalize_iso8601(scanner_start)
            _ne = normalize_iso8601(scanner_end)
            st.caption(f"Будет интерпретировано как: start={_ns}, end={_ne}")
        except Exception:
            pass
        colf1, colf2, colf3 = st.columns(3)
        with colf1:
            scanner_min_growth = st.number_input("Мин. рост, %", value=-100.0, step=1.0, help="0% отсекает все с отрицательной доходностью. Для всех результатов используйте ≤ -100% или ослабьте фильтр.")
        with colf2:
            scanner_min_volume = st.number_input("Мин. объём", value=0.0, step=1000.0)
        with colf3:
            scanner_require_short = st.checkbox("Только шорт‑доступные", value=False)
        sort_key = st.selectbox("Сортировка", options=["growth_pct", "total_volume"], index=0)
        run_scanner = st.button("Запустить сканер")
        st.session_state["_scanner_run"] = run_scanner
        st.session_state["_scanner_spec"] = {
            "symbols": [s.strip() for s in scanner_symbols.split(",") if s.strip()],
            "timeframe": scanner_timeframe,
            "start": scanner_start,
            "end": scanner_end,
            "filters": [
                {"name": "min_growth_pct", "value": scanner_min_growth},
                {"name": "min_volume", "value": scanner_min_volume},
            ],
            "sorts": [{"key": sort_key, "descending": True}],
            "require_short": scanner_require_short,
            "account_id": account_id or None,
        }
        st.markdown("### 💡 Примеры вопросов:")
        st.markdown("""
        - Какая цена Сбербанка?
        - Покажи мой портфель
        - Что в стакане по Газпрому?
        - Покажи свечи YNDX за последние дни
        - Какие у меня активные ордера?
        - Детали моей сессии
        """)

    # Инициализация состояния
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Инициализация Finam API клиента
    finam_client = FinamAPIClient(access_token=api_token or None, base_url=api_base_url if api_base_url else None)
    router = ToolRouter(finam_client, backend=backend)
    audit = get_audit_logger()

    # Проверка токена
    if not finam_client.access_token:
        st.sidebar.warning(
            "⚠️ Finam API токен не установлен. Установите в переменной окружения FINAM_ACCESS_TOKEN или введите выше."
        )
    else:
        st.sidebar.success("✅ Finam API токен установлен")
        # Автоподстановка account_id: .env FINAM_ACCOUNT_ID -> /v1/sessions/details (разные формы)
        try:
            if not st.session_state.get("_account_id_autofill"):
                env_acc = os.getenv("FINAM_ACCOUNT_ID", "").strip()
                if env_acc:
                    st.session_state["_account_id_autofill"] = env_acc
                else:
                    details = finam_client.get_session_details() or {}
                    account_id_found = None
                    # 1) account_ids: ["..."]
                    accs = details.get("account_ids")
                    if isinstance(accs, list) and accs:
                        account_id_found = str(accs[0])
                    # 2) accounts: [ { id | accountId | account_id } ]
                    if not account_id_found:
                        acc_list = details.get("accounts") or details.get("data") or []
                        if isinstance(acc_list, list) and acc_list:
                            first = acc_list[0]
                            if isinstance(first, dict):
                                for k in ("id", "accountId", "account_id"):
                                    if first.get(k):
                                        account_id_found = str(first[k])
                                        break
                    # 3) single fields
                    if not account_id_found:
                        for k in ("id", "accountId", "account_id", "account"):
                            if details.get(k):
                                account_id_found = str(details[k])
                                break
                    if account_id_found:
                        st.session_state["_account_id_autofill"] = account_id_found
        except Exception:
            pass
    # Обновим локальную переменную и сканер-спеку после возможной автозаполнения
    account_id = st.session_state.get("_account_id_autofill", "")
    # Выполним отложенное обновление ID счёта, если запрошено кнопкой
    try:
        if st.session_state.get("_refresh_account") and finam_client.access_token:
            details = finam_client.get_session_details() or {}
            account_id_found = None
            accs = details.get("account_ids")
            if isinstance(accs, list) and accs:
                account_id_found = str(accs[0])
            if not account_id_found:
                acc_list = details.get("accounts") or details.get("data") or []
                if isinstance(acc_list, list) and acc_list:
                    first = acc_list[0]
                    if isinstance(first, dict):
                        for k in ("id", "accountId", "account_id"):
                            if first.get(k):
                                account_id_found = str(first[k])
                                break
            if not account_id_found:
                for k in ("id", "accountId", "account_id", "account"):
                    if details.get(k):
                        account_id_found = str(details[k])
                        break
            if account_id_found:
                st.session_state["_account_id_autofill"] = account_id_found
                account_id = account_id_found
                st.sidebar.success("ID счёта обновлён")
            else:
                st.sidebar.warning("Не удалось найти ID счёта в ответе сессии")
                with st.sidebar.expander("Диагностика сессии", expanded=False):
                    st.json(details)
        st.session_state["_refresh_account"] = False
    except Exception:
        st.session_state["_refresh_account"] = False
    if st.session_state.get("_scanner_spec"):
        st.session_state["_scanner_spec"]["account_id"] = account_id or None

    # Отображение истории сообщений
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                st.markdown("---")

            # Показываем API запросы
            if "api_request" in message:
                with st.expander("🔍 API запрос"):
                    st.code(f"{message['api_request']['method']} {message['api_request']['path']}", language="http")
                    st.json(message["api_request"]["response"])

    # Поле ввода
    if prompt := st.chat_input("Напишите ваш вопрос..."):
        # Добавляем сообщение пользователя
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Формируем историю для LLM (+ контекст с account_id для корректной подстановки)
        conversation_history = [{"role": "system", "content": create_system_prompt()}]
        if account_id:
            conversation_history.append({
                "role": "system",
                "content": f"Контекст: если в запросе требуется идентификатор счёта, используй {account_id}. Если встречается placeholder {'{account_id}'}, подставь это значение."
            })
        for msg in st.session_state.messages:
            conversation_history.append({"role": msg["role"], "content": msg["content"]})

        # Получаем ответ от ассистента
        with st.chat_message("assistant"), st.spinner("Думаю..."):
            try:
                response = call_llm(conversation_history, temperature=0.3)
                assistant_message = response["choices"][0]["message"]["content"]

                # Проверяем API запрос
                method, path = extract_api_request(assistant_message)

                api_data = None
                if method and path:
                    # Подставляем account_id если есть
                    if account_id and "{account_id}" in path:  # noqa: RUF027
                        path = path.replace("{account_id}", account_id)

                    # Показываем что делаем запрос
                    st.info(f"🔍 Выполняю запрос: `{method} {path}`")

                    # Выполняем через оркестрацию
                    ctx = OrchestrationContext(
                        dry_run=False,
                        account_id=account_id or None,
                        confirm=confirm_action,
                    )
                    result = execute_graph(assistant_message, router, ctx)
                    api_response = result.data if result.data is not None else {}
                    if result.api:
                        api_data = {"method": result.api.get("method"), "path": result.api.get("path"), "response": api_response}
                    if result.requires_confirmation:
                        st.warning(result.message or "Требуется подтверждение")
                        with st.expander("🧾 Safety trace", expanded=False):
                            st.json({"recent": audit.recent(20)})
                    # Wise orders insights
                    if result.insights or result.suggestions:
                        with st.expander("💡 Подсказки по исполнению (Wise Orders)", expanded=False):
                            if result.insights:
                                st.json(result.insights)
                            if result.suggestions:
                                st.info(result.suggestions)
                    if result.trace:
                        with st.expander("⏱️ Trace", expanded=False):
                            import os as _os
                            env_info = {
                                "OPENROUTER_API_KEY": "set" if bool(_os.getenv("OPENROUTER_API_KEY")) else "unset",
                                "FINAM_ACCESS_TOKEN": "set" if bool(_os.getenv("FINAM_ACCESS_TOKEN")) else "unset",
                                "FINAM_API_BASE_URL": _os.getenv("FINAM_API_BASE_URL", "") or "https://api.finam.ru",
                            }
                            st.json({"trace": result.trace, "env": env_info})

                    # Проверяем на ошибки
                    if "error" in api_response:
                        st.error(f"⚠️ Ошибка API: {api_response.get('error')}")
                        if "details" in api_response:
                            st.error(f"Детали: {api_response['details']}")

                    # Показываем результат
                    with st.expander("📡 Ответ API", expanded=False):
                        st.json(api_response)

                    # Авто‑график по символу (свечи + объём) для запросов по инструменту
                    try:
                        if result.api and isinstance(result.api.get("path"), str):
                            m = _re.search(r"/v1/instruments/([^/]+)/", result.api.get("path", ""))
                            if m:
                                sym = m.group(1)
                                start_iso = normalize_iso8601("последние 30 дней")
                                end_iso = normalize_iso8601("сегодня")
                                bars_path = f"/v1/instruments/{sym}/bars?timeframe=TIME_FRAME_D&interval.start_time={start_iso}&interval.end_time={end_iso}"
                                raw_bars = router.execute(ToolRequest(method="GET", path=bars_path))
                                # normalize bars list
                                bars = []
                                if isinstance(raw_bars, list):
                                    bars = raw_bars
                                elif isinstance(raw_bars, dict):
                                    for key in ("bars", "candles", "data", "items", "result"):
                                        v = raw_bars.get(key)
                                        if isinstance(v, list):
                                            bars = v
                                            break
                                if bars:
                                    def _num(x: object) -> float:
                                        try:
                                            if isinstance(x, dict):
                                                x = x.get("value")
                                            return float(x) if x is not None else 0.0
                                        except Exception:
                                            return 0.0
                                    opens = [_num(b.get("open") or b.get("o")) for b in bars]
                                    highs = [_num(b.get("high") or b.get("h")) for b in bars]
                                    lows = [_num(b.get("low") or b.get("l")) for b in bars]
                                    closes = [_num(b.get("close") or b.get("c") or b.get("price")) for b in bars]
                                    volumes = [_num(b.get("volume") or b.get("v")) for b in bars]
                                    times_b = [str(b.get("time") or b.get("timestamp") or b.get("date")) for b in bars]
                                    fig_q = make_subplots(rows=1, cols=1, specs=[[{"secondary_y": True}]])
                                    fig_q.add_trace(
                                        go.Candlestick(x=times_b, open=opens, high=highs, low=lows, close=closes, name="Price"),
                                        secondary_y=False,
                                    )
                                    fig_q.add_trace(
                                        go.Bar(x=times_b, y=volumes, name="Volume", marker_color="#aaa", opacity=0.3),
                                        secondary_y=True,
                                    )
                                    fig_q.update_yaxes(title_text="Price", secondary_y=False)
                                    fig_q.update_yaxes(title_text="Volume", secondary_y=True)
                                    fig_q.update_layout(height=360, margin=dict(l=10, r=10, t=20, b=10))
                                    with st.expander("📈 График (30 дней)", expanded=False):
                                        st.plotly_chart(fig_q, use_container_width=True)
                    except Exception:
                        pass

                    api_data = {"method": method, "path": path, "response": api_response}

                    # Добавляем результат в контекст
                    conversation_history.append({"role": "assistant", "content": assistant_message})
                    conversation_history.append({
                        "role": "user",
                        "content": f"Результат API: {json.dumps(api_response, ensure_ascii=False)}\n\nПроанализируй.",
                    })

                    # Получаем финальный ответ
                    response = call_llm(conversation_history, temperature=0.3)
                    assistant_message = response["choices"][0]["message"]["content"]

                st.markdown(assistant_message)
                st.markdown("---")

                # Сохраняем сообщение ассистента
                message_data = {"role": "assistant", "content": assistant_message}
                if api_data:
                    message_data["api_request"] = api_data
                st.session_state.messages.append(message_data)

                # Safety trace всегда доступен
                with st.expander("🧾 Safety trace", expanded=False):
                    st.json({"recent": audit.recent(20)})

            except Exception as e:
                st.error(f"❌ Ошибка: {e}")

    # Render portfolio report if requested
    try:
        if st.session_state.get("_portfolio_run") and account_id:
            st.markdown("## 🧺 Отчет по портфелю")
            snap = get_portfolio_snapshot(router, account_id)  # type: ignore[arg-type]
            fig_sb: object | None = None
            fig_eq: object | None = None
            # Single pie: positions + cash
            pos_nz = [p for p in (snap.positions or []) if (p.market_value or 0) > 0]
            labels = [p.symbol for p in pos_nz]
            values = [p.market_value for p in pos_nz]
            cash_total = sum(snap.cash.values()) if snap.cash else 0.0
            if cash_total > 0:
                labels.append("CASH")
                values.append(cash_total)
            if labels and sum(values) > 0:
                fig_pie = go.Figure(go.Pie(labels=labels, values=values, hole=0.3, name="Portfolio"))
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Нет данных портфеля для диаграммы (позиции/кэш отсутствуют).")

            # Benchmark normalized line (last 60 days)
            start_iso = normalize_iso8601("последние 60 дней")
            end_iso = normalize_iso8601("сегодня")
            bench_sym_input = st.session_state.get("_benchmark_symbol") or "IMOEX@MISX"
            bench_change_pct: float | None = None
            # Подбор бенчмарка и таймфрейма, если дневные бары пусты
            # Build candidate list (deduplicated, order‑preserving)
            raw_candidates = [bench_sym_input, "SBER@MISX", "LQDT@MISX"]
            env_bench = os.getenv("DEFAULT_BENCHMARK_SYMBOLS", "")
            raw_candidates += [s.strip() for s in env_bench.split(",") if s.strip()]
            raw_candidates += ["IMOEX@MISX", "MOEX@MISX", "IMOEX", "SBMX@MISX", "TMOS@MISX", "FXRL@MISX"]
            seen: set[str] = set()
            candidates: list[str] = []
            for c in raw_candidates:
                if c and c not in seen:
                    candidates.append(c)
                    seen.add(c)
            picked_sym = None
            xs_bm, ys_bm, o_bm, h_bm, l_bm, c_bm = [], [], [], [], [], []
            bm_try_paths: list[str] = []

            # Helper to normalize bars list from various shapes
            def _bars_list(raw: object) -> list:
                if isinstance(raw, list):
                    return raw
                if isinstance(raw, dict):
                    for k in ("bars", "candles", "data", "items", "result"):
                        v = raw.get(k)  # type: ignore[call-arg]
                        if isinstance(v, list):
                            return v
                return []
            for sym in candidates:
                for tf in ("TIME_FRAME_D", "TIME_FRAME_W", "TIME_FRAME_MN"):
                    try:
                        # Try instruments path first
                        path_bm = f"/v1/instruments/{sym}/bars?timeframe={tf}&interval.start_time={start_iso}&interval.end_time={end_iso}"
                        bm_try_paths.append(path_bm)
                        raw_bm = router.execute(ToolRequest(method="GET", path=path_bm))
                        bm_bars = _bars_list(raw_bm)
                        xs_bm, ys_bm, o_bm, h_bm, l_bm, c_bm = [], [], [], [], [], []
                        for b in bm_bars:
                            t = str(b.get("time") or b.get("timestamp") or b.get("date"))
                            c = b.get("close") or b.get("c") or b.get("price")
                            try:
                                ys_bm.append(float(c)); xs_bm.append(t)
                                o_bm.append(float(b.get("open") or b.get("o") or c))
                                h_bm.append(float(b.get("high") or b.get("h") or c))
                                l_bm.append(float(b.get("low") or b.get("l") or c))
                                c_bm.append(float(c))
                            except Exception:
                                continue
                        if ys_bm:
                            picked_sym = f"{sym}"
                            break
                        # If empty, try assets path variant
                        path_bm2 = f"/v1/assets/{sym}/bars?timeframe={tf}&interval.start_time={start_iso}&interval.end_time={end_iso}"
                        bm_try_paths.append(path_bm2)
                        raw_bm2 = router.execute(ToolRequest(method="GET", path=path_bm2))
                        bm_bars2 = _bars_list(raw_bm2)
                        xs_bm, ys_bm, o_bm, h_bm, l_bm, c_bm = [], [], [], [], [], []
                        for b in bm_bars2:
                            t = str(b.get("time") or b.get("timestamp") or b.get("date"))
                            c = b.get("close") or b.get("c") or b.get("price")
                            try:
                                ys_bm.append(float(c)); xs_bm.append(t)
                                o_bm.append(float(b.get("open") or b.get("o") or c))
                                h_bm.append(float(b.get("high") or b.get("h") or c))
                                l_bm.append(float(b.get("low") or b.get("l") or c))
                                c_bm.append(float(c))
                            except Exception:
                                continue
                        if ys_bm:
                            picked_sym = f"{sym}"
                            break
                    except Exception:
                        continue
                if picked_sym:
                    break
            if ys_bm:
                try:
                    bench_change_pct = (ys_bm[-1] - ys_bm[0]) / ys_bm[0] * 100.0
                except Exception:
                    bench_change_pct = None
                st.subheader(f"Бенчмарк: {picked_sym or bench_sym_input} {('+' if (bench_change_pct or 0)>=0 else '')}{(bench_change_pct or 0):.1f}% за 60д")
                if c_bm and o_bm and h_bm and l_bm:
                    fig_bm_c = make_subplots(rows=1, cols=1, specs=[[{"secondary_y": False}]])
                    fig_bm_c.add_trace(go.Candlestick(x=xs_bm, open=o_bm, high=h_bm, low=l_bm, close=c_bm, name=f"{picked_sym or bench_sym_input}"))
                    fig_bm_c.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10))
                    st.plotly_chart(fig_bm_c, use_container_width=True)
                base = ys_bm[0]
                yn = [v / base * 100.0 for v in ys_bm]
                fig_bm = go.Figure(go.Scatter(x=xs_bm, y=yn, name=f"{picked_sym or bench_sym_input} (норм=100)"))
                fig_bm.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10))
                st.plotly_chart(fig_bm, use_container_width=True)
                fig_eq = fig_bm
            else:
                # Явный маркер отсутствия данных по бенчмарку + попытки
                st.caption(f"Нет данных баров для бенчмарка среди кандидатов: {', '.join(candidates)}. Проверьте символ.")
                with st.expander("ℹ️ Диагностика бенчмарка", expanded=False):
                    for p in bm_try_paths[:6]:
                        st.code(f"GET {p}")

            # OHLCV per asset (up to 6)
            def _num(x: object) -> float:
                try:
                    if isinstance(x, dict):
                        x = x.get("value")
                    return float(x) if x is not None else 0.0
                except Exception:
                    return 0.0

            for p in pos_nz[:6]:
                try:
                    path_bars = f"/v1/instruments/{p.symbol}/bars?timeframe=TIME_FRAME_D&interval.start_time={start_iso}&interval.end_time={end_iso}"
                    raw_bars = router.execute(ToolRequest(method="GET", path=path_bars))
                    bars = _bars_list(raw_bars)
                    if not bars:
                        # try assets path variant
                        path_bars2 = f"/v1/assets/{p.symbol}/bars?timeframe=TIME_FRAME_D&interval.start_time={start_iso}&interval.end_time={end_iso}"
                        raw_bars2 = router.execute(ToolRequest(method="GET", path=path_bars2))
                        bars = _bars_list(raw_bars2)
                    if not bars:
                        continue
                    opens = [_num(b.get("open") or b.get("o")) for b in bars]
                    highs = [_num(b.get("high") or b.get("h")) for b in bars]
                    lows = [_num(b.get("low") or b.get("l")) for b in bars]
                    closes = [_num(b.get("close") or b.get("c") or b.get("price")) for b in bars]
                    volumes = [_num(b.get("volume") or b.get("v")) for b in bars]
                    times_b = [str(b.get("time") or b.get("timestamp") or b.get("date")) for b in bars]
                    fig_q = make_subplots(rows=1, cols=1, specs=[[{"secondary_y": True}]])
                    fig_q.add_trace(go.Candlestick(x=times_b, open=opens, high=highs, low=lows, close=closes, name=f"{p.symbol}"), secondary_y=False)
                    fig_q.add_trace(go.Bar(x=times_b, y=volumes, name="Volume", marker_color="#aaa", opacity=0.3), secondary_y=True)
                    fig_q.update_yaxes(title_text="Price", secondary_y=False)
                    fig_q.update_yaxes(title_text="Volume", secondary_y=True)
                    fig_q.update_layout(height=360, margin=dict(l=10, r=10, t=20, b=10))
                    st.plotly_chart(fig_q, use_container_width=True)
                except Exception:
                    continue

            # Diagnostics + LLM краткий совет по распределению
            try:
                total_mv = sum(values) if values else 0.0
                diag_positions = [
                    {"symbol": p.symbol, "market_value": round(p.market_value, 2)} for p in pos_nz
                ]
                diag = {
                    "equity_est": round((total_mv + cash_total), 2),
                    "cash_total": round(cash_total, 2),
                    "positions": diag_positions,
                }
                with st.expander("ℹ️ Диагностика портфеля", expanded=True):
                    st.json(diag)

                # Сформируем конкретный совет через LLM: коротко и с числами/символами
                try:
                    weights = [(p['symbol'], round((p['market_value']/(total_mv or 1))*100, 1)) for p in diag_positions]
                    weights_sorted = sorted(weights, key=lambda x: x[1], reverse=True)
                    weights_str = ", ".join(f"{sym}: {pct}%" for sym, pct in weights_sorted)
                    top_sym = weights_sorted[0][0] if weights_sorted else "—"
                    cash_pct = round((cash_total/(((total_mv or 0)+cash_total) or 1))*100, 1)
                    bench_ctx = f"Бенчмарк {picked_sym or bench_sym_input}: {('+' if (bench_change_pct or 0)>=0 else '')}{(bench_change_pct or 0):.1f}% за 60д" if bench_change_pct is not None else f"Бенчмарк {picked_sym or bench_sym_input}: нет данных"
                    prompt_advice = (
                        "Дано распределение портфеля и бенчмарк. Напиши краткий аналитический комментарий (2–4 коротких предложения) и практические рекомендации. "
                        "Избегай общих фраз; ссылайся на символы/доли/кэш по мере уместности. Формат свободный, без преамбулы.\n\n"
                        f"Контекст: {bench_ctx}. Позиции: {weights_str or '—'}. Кэш: {cash_pct}%. Топ: {top_sym}."
                    )
                    resp = call_llm([{"role": "user", "content": prompt_advice}], temperature=0.2)
                    advice = resp["choices"][0]["message"]["content"].strip()
                    if advice:
                        st.success(advice)
                        with st.expander("LLM совет (trace)", expanded=False):
                            st.markdown("Промпт:")
                            st.code(prompt_advice)
                            st.markdown("Ответ:")
                            st.write(advice)
                except Exception:
                    pass
            except Exception:
                pass

            # (убрано дублирующееся окно диагностики)

            # Export buttons
            export_dir = "reports"
            os.makedirs(export_dir, exist_ok=True)
            col1, col2 = st.columns(2)
            with col1:
                if fig_sb is not None and st.button("💾 Сохранить Sunburst (HTML)"):
                    fig_sb.write_html(os.path.join(export_dir, "portfolio_sunburst.html"))
                    st.success("Сохранено: reports/portfolio_sunburst.html")
            with col2:
                if fig_eq is not None and st.button("🖼️ Сохранить Equity (PNG)"):
                    fig_eq.write_image(os.path.join(export_dir, "portfolio_equity.png"))
                    st.success("Сохранено: reports/portfolio_equity.png")
    except Exception as e:
        st.error(f"❌ Ошибка отчета портфеля: {e}")
        # Диагностика
        try:
            details = finam_client.get_session_details()
        except Exception:
            details = {}
        with st.expander("ℹ️ Диагностика портфеля", expanded=True):
            st.json({
                "account_id": account_id,
                "session_details_preview": details,
            })

    # Run backtest preset if requested
    try:
        if st.session_state.get("_backtest_run") and st.session_state.get("_backtest_preset_name"):
            st.markdown("## 🧪 Бэктест (пресет)")
            name = st.session_state.get("_backtest_preset_name")
            # find preset
            cfg_list = (strat_cfg or {}).get("strategies", [])
            preset = next((s for s in cfg_list if s.get("name") == name), None)
            if preset:
                from src.app.backtest.dsl import parse_strategy
                from src.app.backtest.executor import run_backtest

                strat = parse_strategy(preset)
                res = run_backtest(router, strat)
                if res.metrics.get("error"):
                    st.error("Нет ценовых данных для выбранных параметров бэктеста")
                    with st.expander("ℹ️ Диагностика", expanded=True):
                        st.json(res.metrics)
                    return
                # Compact metrics formatting
                mp = {
                    "final_equity": round(res.metrics.get("final_equity", 0.0), 2),
                    "return_pct": f"{res.metrics.get('return_pct', 0.0):.2f}%",
                    "max_drawdown_pct": f"{res.metrics.get('max_drawdown_pct', 0.0):.2f}%",
                }
                st.json(mp)
                fig_bt = store_backtest_result(
                    res.metrics,
                    res.equity_curve,
                    res.times,
                    res.closes,
                    res.trades,
                    res.opens,
                    res.highs,
                    res.lows,
                    res.volumes,
                )
                st.plotly_chart(fig_bt, use_container_width=True)
                st.session_state["_bt_trades"] = res.trades
            else:
                st.info("Выберите пресет стратегии")

        # Execute deferred custom backtest (from sidebar), after router is ready
        if st.session_state.get("_run_custom_bt") and st.session_state.get("_custom_bt_cfg"):
            st.markdown("## 🧪 Бэктест (кастом)")
            try:
                from src.app.backtest.dsl import parse_strategy
                from src.app.backtest.executor import run_backtest

                cfg_dict = st.session_state.get("_custom_bt_cfg")
                strat = parse_strategy(cfg_dict)
                res = run_backtest(router, strat)
                if res.metrics.get("error"):
                    st.error("Нет ценовых данных для выбранных параметров")
                    with st.expander("ℹ️ Диагностика", expanded=True):
                        st.json(res.metrics)
                else:
                    mp2 = {
                        "final_equity": round(res.metrics.get("final_equity", 0.0), 2),
                        "return_pct": f"{res.metrics.get('return_pct', 0.0):.2f}%",
                        "max_drawdown_pct": f"{res.metrics.get('max_drawdown_pct', 0.0):.2f}%",
                    }
                    st.json(mp2)
                    fig_bt2 = store_backtest_result(
                        res.metrics,
                        res.equity_curve,
                        res.times,
                        res.closes,
                        res.trades,
                        res.opens,
                        res.highs,
                        res.lows,
                        res.volumes,
                    )
                    st.plotly_chart(fig_bt2, use_container_width=True)
                    st.session_state["_bt_trades"] = res.trades
                st.session_state["_run_custom_bt"] = False
            except Exception as e:  # noqa: BLE001
                st.error(f"Ошибка кастомного бэктеста: {e}")
    except Exception as e:
        st.error(f"❌ Ошибка бэктеста: {e}")

    # Unified export section for last backtest result
    try:
        from src.app.backtest.ui import render_backtest_export as _render_bt
        trades = st.session_state.get("_bt_trades")
        _render_bt(trades)
    except Exception:
        pass

    # Run scanner if requested
    try:
        if st.session_state.get("_scanner_run"):
            st.markdown("## 🔎 Результаты сканера")
            ss = st.session_state.get("_scanner_spec") or {}
            # Normalize simple tickers to market symbols (SBER -> SBER@MISX)
            from src.app.core.normalize import infer_market_symbol as _infer_market_symbol
            _raw_syms = ss.get("symbols", ["SBER", "GAZP"]) or []
            _norm_syms = [_infer_market_symbol(s) for s in _raw_syms]

            spec = ScreenSpec(
                symbols=_norm_syms,
                timeframe=ss.get("timeframe", "TIME_FRAME_D"),
                start=ss.get("start", "последние 30 дней"),
                end=ss.get("end", "сегодня"),
                filters=[FilterSpec(**f) for f in ss.get("filters", [])],
                sorts=[SortSpec(**s) for s in ss.get("sorts", [])],
                require_short=bool(ss.get("require_short", False)),
                account_id=ss.get("account_id"),
            )
            results, meta = run_screen(router, spec, page=1, page_size=100)
            # Table
            import pandas as pd
            if results:
                def _fmt_int(v: object) -> str:
                    try:
                        x = float(v)
                        return f"{int(x):,}".replace(",", " ")
                    except Exception:
                        return "—"

                def _fmt_pct(v: object) -> str:
                    try:
                        return f"{float(v):.2f}%"
                    except Exception:
                        return "—"

                df_display = pd.DataFrame([
                    {
                        "symbol": r.symbol,
                        "growth %": _fmt_pct(r.growth_pct),
                        "volume": _fmt_int(r.total_volume),
                    }
                    for r in results
                ])
                st.dataframe(df_display, use_container_width=True)
                # OHLCV candlesticks per result (limit for UI)
                try:
                    from plotly.subplots import make_subplots as _make_subplots
                    import plotly.graph_objects as _go
                    start_iso = normalize_iso8601(spec.start)
                    end_iso = normalize_iso8601(spec.end)
                    shown = 0
                    for r in results:
                        if shown >= 6:
                            break
                        try:
                            path_bars = f"/v1/instruments/{r.symbol}/bars?timeframe={spec.timeframe}&interval.start_time={start_iso}&interval.end_time={end_iso}"
                            raw_bars = router.execute(ToolRequest(method="GET", path=path_bars))
                            bars = []
                            if isinstance(raw_bars, list):
                                bars = raw_bars
                            elif isinstance(raw_bars, dict):
                                for key in ("bars", "candles", "data", "items", "result"):
                                    v = raw_bars.get(key)
                                    if isinstance(v, list):
                                        bars = v
                                        break
                            if not bars:
                                # try assets path
                                path_bars2 = f"/v1/assets/{r.symbol}/bars?timeframe={spec.timeframe}&interval.start_time={start_iso}&interval.end_time={end_iso}"
                                raw_bars2 = router.execute(ToolRequest(method="GET", path=path_bars2))
                                if isinstance(raw_bars2, list):
                                    bars = raw_bars2
                                elif isinstance(raw_bars2, dict):
                                    for key in ("bars", "candles", "data", "items", "result"):
                                        v = raw_bars2.get(key)
                                        if isinstance(v, list):
                                            bars = v
                                            break
                            if not bars:
                                continue
                            def _num(x: object) -> float:
                                try:
                                    if isinstance(x, dict):
                                        x = x.get("value")
                                    return float(x) if x is not None else 0.0
                                except Exception:
                                    return 0.0
                            opens = [_num(b.get("open") or b.get("o")) for b in bars]
                            highs = [_num(b.get("high") or b.get("h")) for b in bars]
                            lows = [_num(b.get("low") or b.get("l")) for b in bars]
                            closes = [_num(b.get("close") or b.get("c") or b.get("price")) for b in bars]
                            volumes = [_num(b.get("volume") or b.get("v")) for b in bars]
                            times_b = [str(b.get("time") or b.get("timestamp") or b.get("date")) for b in bars]
                            fig_q = _make_subplots(rows=1, cols=1, specs=[[{"secondary_y": True}]])
                            fig_q.add_trace(_go.Candlestick(x=times_b, open=opens, high=highs, low=lows, close=closes, name=f"{r.symbol}"), secondary_y=False)
                            fig_q.add_trace(_go.Bar(x=times_b, y=volumes, name="Volume", marker_color="#aaa", opacity=0.3), secondary_y=True)
                            fig_q.update_yaxes(title_text="Price", secondary_y=False)
                            fig_q.update_yaxes(title_text="Volume", secondary_y=True)
                            fig_q.update_layout(height=360, margin=dict(l=10, r=10, t=20, b=10))
                            st.plotly_chart(fig_q, use_container_width=True)
                            shown += 1
                        except Exception:
                            continue
                except Exception:
                    pass
                # Short LLM summary based on table (symbols, growth %, volume)
                try:
                    rows_ctx = []
                    for r in results[:8]:
                        g = r.growth_pct if r.growth_pct is not None else 0.0
                        v = r.total_volume if r.total_volume is not None else 0.0
                        rows_ctx.append({"symbol": r.symbol, "growth_pct": round(float(g), 2), "volume": float(v)})
                    if rows_ctx:
                        # Compose compact context string
                        ctx_str = ", ".join(
                            f"{row['symbol']}: {row['growth_pct']:+.2f}% vol {int(row['volume']):,}".replace(",", " ")
                            for row in rows_ctx
                        )
                        prompt_scan = (
                            "Ты аналитик рынка. По результатам сканера сформулируй 2–4 коротких предложения: вывод по динамике и ликвидности, конкретные тикеры и практические шаги. "
                            "Избегай общих фраз и вступлений, сразу по делу.\n\n"
                            f"Данные: {ctx_str}."
                        )
                        resp = call_llm([{"role": "user", "content": prompt_scan}], temperature=0.2)
                        advice = resp["choices"][0]["message"]["content"].strip()
                        if advice:
                            st.success(advice)
                            with st.expander("LLM комментарий (сканер)", expanded=False):
                                st.markdown("Промпт:")
                                st.code(prompt_scan)
                                st.markdown("Ответ:")
                                st.write(advice)
                except Exception:
                    pass
            else:
                st.info("Пустой результат сканера. Попробуйте ослабить фильтры или изменить период/универс.")
                with st.expander("ℹ️ Диагностика", expanded=True):
                    try:
                        _ns = normalize_iso8601(spec.start)
                        _ne = normalize_iso8601(spec.end)
                    except Exception:
                        _ns = spec.start
                        _ne = spec.end
                    st.json({
                        "symbols": spec.symbols,
                        "timeframe": spec.timeframe,
                        "start": spec.start,
                        "end": spec.end,
                        "normalized": {"start": _ns, "end": _ne},
                        "filters": [f.__dict__ for f in spec.filters],
                        "account_id": spec.account_id,
                    })
                    # Low-noise raw probe for first symbol
                    try:
                        if spec.symbols:
                            sym0 = spec.symbols[0]
                            path0 = f"/v1/instruments/{sym0}/bars?timeframe={spec.timeframe}&interval.start_time={_ns}&interval.end_time={_ne}"
                            raw = router.execute(ToolRequest(method="GET", path=path0))
                            preview = raw[:3] if isinstance(raw, list) else (raw.get("bars") or raw.get("data") or raw)
                            st.code(f"GET {path0}")
                            st.json({"raw_type": str(type(raw)), "preview": preview})
                    except Exception as _e:  # noqa: BLE001
                        st.warning(f"Raw probe error: {_e}")
            if st.button("📄 Export CSV (scanner)"):
                os.makedirs("reports", exist_ok=True)
                csv_path = "reports/scanner_results.csv"
                try:
                    # export the displayed dataframe
                    if 'df_display' in locals():
                        df_display.to_csv(csv_path, index=False)
                        st.success(csv_path)
                    else:
                        st.warning("Нет данных для экспорта")
                except Exception:
                    st.warning("Нет данных для экспорта")
    except Exception as e:
        st.error(f"❌ Ошибка сканера: {e}")


if __name__ == "__main__":
    main()
