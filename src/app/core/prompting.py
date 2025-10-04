from __future__ import annotations

from typing import List, Iterable

from src.app.registry.endpoints import EndpointRegistry, _extract_placeholders


def system_prompt_for_mapping() -> str:
    return (
        "Ты — маршрутизатор Finam TradeAPI. На вход — вопрос на русском. На выход — строго METHOD и PATH.\n"
        "Используй только перечисленные endpoint’ы. Не выдумывай параметры. Если не хватает данных — укажи плейсхолдер {slot} в пути.\n"
        "Формат ответа: 'GET /v1/...', 'POST /v1/...' или 'DELETE /v1/...'.\n\n"
        "Правила маппинга (важно):\n"
        "- Если в тексте есть шаблон ORD123456 → 'DELETE /v1/accounts/{account_id}/orders/{order_id}'.\n"
        "- 'опцион'/'цепочка опционов' → '/v1/assets/{symbol}/options'.\n"
        "- 'расписан'/'клиринг' → '/v1/assets/{symbol}/schedule'.\n"
        "- 'параметр'/'лот'/'шаг цен'/'ГО'/'ставка риск' → '/v1/assets/{symbol}/params' (+ '?account_id=...' если указан счёт).\n"
        "- 'когда истекает фьючерс' → '/v1/assets/{symbol}' (информация об инструменте).\n"
        "- 'история сделок по счёту' → '/v1/accounts/{account_id}/trades' с query 'interval.start_time'/'interval.end_time'.\n"
        "- 'лента/последние сделки по инструменту' → '/v1/instruments/{symbol}/trades/latest'.\n"
        "- Свечи '/v1/instruments/{symbol}/bars': timeframe=TIME_FRAME_*, даты только как 'interval.start_time'/'interval.end_time'. Не используйте ключи 'start'/'end'.\n"
        "- Тикер: используй ровно тот ticker из вопроса (например 'SBER@MISX'). Если в вопросе только имя, возьми из Known symbols. Не подставляй ISIN/синонимы или другие рынки.\n"
    )


def endpoints_spec() -> str:
    """Build endpoint list and slot hints from declarative registry (SSOT)."""
    reg = EndpointRegistry()
    items = reg.list_items()
    lines: List[str] = ["API Documentation:"]
    for item in items:
        method = item["method"]
        path = item["path"]
        lines.append(f"- {method} {path}")
        # slots from path and params
        slots = set()
        for seg in _extract_placeholders(path):
            slots.add(seg.rstrip("?"))
        for _, tmpl in (item.get("params", {}) or {}).items():
            for seg in _extract_placeholders(str(tmpl)):
                slots.add(seg.rstrip("?"))
        if slots:
            # types from slot_types
            types = item.get("slot_types", {}) or {}
            table = ["    slot | required | type", "    ---- | -------- | ----"]
            for s in sorted(slots):
                required = "yes" if ("{" + s + "}" in path or any(("{" + s + "}" in str(v)) and not str(v).endswith("?}") for v in (item.get("params", {}) or {}).values())) else "no"
                stype = types.get(s, "string")
                table.append(f"    {s} | {required} | {stype}")
            lines.extend(table)
    # Common timeframe hint
    lines.append(
        "\nTimeframes: TIME_FRAME_M1, TIME_FRAME_M5, TIME_FRAME_M15, TIME_FRAME_M30, TIME_FRAME_H1, TIME_FRAME_H4, TIME_FRAME_D, TIME_FRAME_W, TIME_FRAME_MN"
    )
    # Guidance: choose from known symbols if present in the user question
    lines.append("\nЕсли символ не указан — выбери из списка известных символов ниже или укажи плейсхолдер {symbol}.")
    return "\n".join(lines)


def symbols_spec(symbols: Iterable[str], limit: int = 100) -> str:
    uniq = []
    seen = set()
    for s in symbols:
        s = (s or "").strip()
        if not s:
            continue
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
        if len(uniq) >= limit:
            break
    if not uniq:
        return ""
    return "\nKnown symbols (use if relevant):\n- " + ", ".join(uniq)


def fewshot_examples(pairs: List[dict[str, str]]) -> str:
    buf: List[str] = []
    for ex in pairs:
        buf.append(f"Вопрос: \"{ex['question']}\"")
        buf.append(f"Ответ: {ex['type']} {ex['request']}")
        buf.append("")
    return "\n".join(buf)


def disambiguation_prompt(missing_fields: List[str]) -> str:
    need = ", ".join(missing_fields)
    return (
        "Не хватает данных для выполнения запроса. Уточните, пожалуйста: "
        f"{need}. Ответьте кратко, только недостающие значения."
    )


def extraction_prompt() -> str:
    return (
        "Определите intent и извлеките параметры из запроса. Допустимые intent: "
        "quote, orderbook, bars, trades_latest, account, orders_list, order_get, trades, transactions, "
        "session_details, session_create, order_create, order_cancel.\n"
        "Верните JSON вида: {\"intent\": str, ...поля...}.\n"
        "Поля: symbol, timeframe (TIME_FRAME_*), start (ISO8601), end (ISO8601), account_id, order_id, "
        "limit, side, type, quantity, price, stop_price, time_in_force. Возвращайте ТОЛЬКО найденные поля."
    )


