#!/usr/bin/env python3
"""
Скрипт для генерации submission.csv на основе test.csv

Использует LLM для преобразования вопросов на естественном языке
в HTTP запросы к Finam TradeAPI.

Использование:
    python scripts/generate_submission.py [OPTIONS]

Опции:
    --test-file PATH      Путь к test.csv (по умолчанию: data/processed/test.csv)
    --train-file PATH     Путь к train.csv (по умолчанию: data/processed/train.csv)
    --output-file PATH    Путь к submission.csv (по умолчанию: data/processed/submission.csv)
    --num-examples INT    Количество примеров для few-shot (по умолчанию: 10)
    --batch-size INT      Размер батча для обработки (по умолчанию: 5)
"""

import csv
import os
import sys
import random
from pathlib import Path

import click
try:
    from tqdm import tqdm  # type: ignore[import-untyped]
except Exception:  # pragma: no cover
    def tqdm(iterable, desc: str = ""):
        return iterable

# Ensure project root is importable for `src` package
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.app.core.llm import call_llm
from src.app.core.prompting import system_prompt_for_mapping, endpoints_spec, symbols_spec
from src.app.core.normalize import parse_date_range
from src.app.core.symbols import SymbolResolver
from src.app.registry.endpoints import EndpointRegistry
from src.app.orchestration.extractor import extract_structured
from src.app.orchestration.endpoints import build_from_schema


def calculate_cost(usage: dict, model: str) -> float:
    """Рассчитать стоимость запроса на основе usage и модели"""
    # Цены OpenRouter (примерные, в $ за 1M токенов)
    # Источник: https://openrouter.ai/models
    pricing = {
        "openai/gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
        "openai/gpt-4o": {"prompt": 2.50, "completion": 10.00},
        "openai/gpt-3.5-turbo": {"prompt": 0.50, "completion": 1.50},
        "anthropic/claude-3-sonnet": {"prompt": 3.00, "completion": 15.00},
        "anthropic/claude-3-haiku": {"prompt": 0.25, "completion": 1.25},
    }

    # Получаем цены для модели (по умолчанию как для gpt-4o-mini)
    prices = pricing.get(model, {"prompt": 0.15, "completion": 0.60})

    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)

    # Считаем стоимость (цена за 1M токенов)
    prompt_cost = (prompt_tokens / 1_000_000) * prices["prompt"]
    completion_cost = (completion_tokens / 1_000_000) * prices["completion"]

    return prompt_cost + completion_cost


def _classify_request(path: str) -> str:
    if path.startswith("/v1/instruments/") and "/quotes/latest" in path:
        return "quotes"
    if path.startswith("/v1/instruments/") and "/orderbook" in path:
        return "orderbook"
    if path.startswith("/v1/instruments/") and "/bars" in path:
        return "bars"
    if path.startswith("/v1/instruments/") and "/trades/latest" in path:
        return "trades_latest"
    if path.startswith("/v1/accounts/") and "/orders" in path and path.count("/") == 4:
        return "orders_list"
    if path.startswith("/v1/accounts/") and "/orders/" in path and path.count("/") == 5:
        return "order_get"
    if path.startswith("/v1/accounts/") and "/trades" in path:
        return "account_trades"
    if path.startswith("/v1/accounts/") and "/transactions" in path:
        return "transactions"
    if path.startswith("/v1/assets/") and "/params" in path:
        return "asset_params"
    if path.startswith("/v1/assets/") and "/options" in path:
        return "asset_options"
    if path == "/v1/assets":
        return "assets"
    if path == "/v1/exchanges":
        return "exchanges"
    if path == "/v1/sessions" or path == "/v1/sessions/details":
        return "sessions"
    return "other"


def load_train_examples(train_file: Path, num_examples: int = 10) -> list[dict[str, str]]:
    """Загрузить примеры из train.csv с равномерным покрытием категорий endpoint'ов."""
    rows: list[dict[str, str]] = []
    with open(train_file, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            rows.append({"question": row["question"], "type": row["type"], "request": row["request"]})

    # Группируем по категориям схем с помощью реестра (по шаблонам пути)
    reg = EndpointRegistry()
    by_cat: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        schema = reg.classify_path(r["request"]) or _classify_request(r["request"])  # fallback
        by_cat.setdefault(schema, []).append(r)

    # Желаемое покрытие
    # Приоритет — схемы из реестра, затем прочее
    priority: list[str] = []
    import yaml  # type: ignore
    with open(reg.config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for it in cfg.get("endpoints", []):
        priority.append(it.get("schema"))
    priority.append("other")

    selected: list[dict[str, str]] = []
    per_cat = max(1, num_examples // max(1, len(priority)))
    for cat in priority:
        pool = by_cat.get(cat, [])
        if not pool:
            continue
        k = min(per_cat, len(pool))
        selected.extend(random.sample(pool, k))

    # Если не добрали, дозаполним из оставшегося
    if len(selected) < num_examples:
        rest = [r for r in rows if r not in selected]
        k = min(num_examples - len(selected), len(rest))
        if k > 0:
            selected.extend(random.sample(rest, k))

    return selected[:num_examples]


def _collect_symbols_from_train(train_file: Path) -> list[str]:
    syms: list[str] = []
    import re as _re
    with open(train_file, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            q = (row.get("question") or "")
            for tok in set(_re.findall(r"\b[A-Z0-9]{2,12}(?:@[A-Z]{2,8})?\b", q.upper())):
                if _re.fullmatch(r"ORD\d+", tok):
                    continue
                if tok.isdigit():
                    continue
                syms.append(tok)
    return syms


def create_prompt(question: str, examples: list[dict[str, str]], train_file: Path) -> str:
    """Создать промпт для LLM с few-shot примерами"""
    prompt = (
        system_prompt_for_mapping()
        + "\n\n"
        + endpoints_spec()
        + "\n\n"
        + symbols_spec(_collect_symbols_from_train(train_file))
        + "\n\nПримеры:\n\n"
    )

    for ex in examples:
        prompt += f'Вопрос: "{ex["question"]}"\n'
        prompt += f"Ответ: {ex['type']} {ex['request']}\n\n"

    prompt += f'Вопрос: "{question}"\n'
    prompt += "Ответ (только HTTP метод и путь, без объяснений):"

    return prompt


def parse_llm_response(response: str) -> tuple[str, str]:
    """Парсинг ответа LLM в (type, request)"""
    response = response.strip()

    # Ищем HTTP метод в начале
    methods = ["GET", "POST", "DELETE", "PUT", "PATCH"]
    method = "GET"  # по умолчанию
    request = response

    for m in methods:
        if response.upper().startswith(m):
            method = m
            request = response[len(m) :].strip()
            break

    # Убираем лишние символы
    request = request.strip()
    if not request.startswith("/"):
        # Если LLM вернул что-то странное, пытаемся найти путь
        parts = request.split()
        for part in parts:
            if part.startswith("/"):
                request = part
                break

    # Fallback на безопасный вариант
    if not request.startswith("/"):
        request = "/v1/assets"

    return method, request


def _extract_account_id(text: str) -> str | None:
    import re
    U = (text or "").upper()
    # FIN-203-B, ACC-001-A, USR-305-C
    m = re.search(r"\b(?:ACC|USR|FIN)-\d{3}-[A-Z]\b", U)
    if m:
        return m.group(0)
    # A12345, B98765, C54321, etc.
    m = re.search(r"\b[A-Z]\d{5,}\b", U)
    if m:
        return m.group(0)
    # plain number (last resort)
    m = re.search(r"\b\d{3,}\b", U)
    if m:
        return m.group(0)
    return None


def _extract_order_id(text: str) -> str | None:
    import re
    U = (text or "").upper()
    m = re.search(r"\bORD[A-Z0-9-]*\b", U)
    if m:
        return m.group(0)
    return None


def _extract_symbol(text: str) -> str | None:
    import re
    U = (text or "").upper()
    # Prefer tokens with '@' first
    tokens = re.findall(r"\b[A-Z0-9]{2,12}(?:@[A-Z]{2,8})?\b", U)
    for tok in tokens:
        if tok.startswith("ORD"):
            continue
        if "@" in tok:
            return tok
    for tok in tokens:
        if tok.startswith("ORD"):
            continue
        return tok
    return None


def _postprocess_request(question: str, method: str, path: str) -> str:
    """Fill placeholders in the generated path using cues from the question."""
    if not path:
        return path
    acc = _extract_account_id(question)
    if acc:
        path = path.replace("{account_id}", acc)
        # also replace query param placeholder if present
        path = path.replace("account_id={account_id}", f"account_id={acc}")
    order_id = _extract_order_id(question)
    if order_id:
        path = path.replace("{order_id}", order_id)
    sym = _extract_symbol(question)
    if sym:
        path = path.replace("/{symbol}", f"/{sym}")
    # Handle {slot} for intervals using parse_date_range
    if "{slot}" in path:
        rng = parse_date_range(question)
        if rng:
            start, end = rng
            # replace first then second occurrence
            if "interval.start_time={slot}" in path:
                path = path.replace("interval.start_time={slot}", f"interval.start_time={start}")
            else:
                path = path.replace("{slot}", start, 1)
            if "interval.end_time={slot}" in path:
                path = path.replace("interval.end_time={slot}", f"interval.end_time={end}")
            else:
                path = path.replace("{slot}", end, 1)
    return path


def generate_api_call(question: str, examples: list[dict[str, str]], model: str, train_file: Path, force_llm: bool = False) -> tuple[dict[str, str], float]:
    """Сгенерировать API запрос для вопроса

    Returns:
        tuple: (result_dict, cost_in_dollars)
    """
    # First try: structured extractor (deterministic) unless LLM is forced
    if not force_llm:
        schema, missing = extract_structured(question)
        if schema and not missing:
            method, path, params = build_from_schema(schema)
            if params:
                # inline query if needed for leaderboard path
                if method == "GET" and path and "?" not in path:
                    query = "&".join(f"{k}={v}" for k, v in params.items())
                    path = f"{path}?{query}"
            # post-process placeholders
            path = _postprocess_request(question, method, path)
            return {"type": method, "request": path, "_source": "structured"}, 0.0

    # Fallback: LLM prompt mapping
    prompt = create_prompt(question, examples, train_file)
    messages = [{"role": "user", "content": prompt}]
    try:
        response = call_llm(messages, temperature=0.0, max_tokens=200)
        llm_answer = response["choices"][0]["message"]["content"].strip()
        method, request = parse_llm_response(llm_answer)
        # Validate via registry classification and fallback to offline mapping when invalid
        reg = EndpointRegistry()
        if not request.startswith("/") or reg.classify_path(request) is None:
            # Try deterministic offline mapping
            from src.app.leaderboard.offline_map import offline_map
            mapped = offline_map(question)
            if mapped:
                method, request = mapped
        usage = response.get("usage", {})
        cost = calculate_cost(usage, model)
        # post-process placeholders
        request = _postprocess_request(question, method, request)
        # mark source for debugging
        src = "llm" if reg.classify_path(request) is not None else "offline"
        return {"type": method, "request": request, "_llm": llm_answer, "_source": src}, cost

    except Exception as e:
        click.echo(f"⚠️  Ошибка при генерации для вопроса '{question[:50]}...': {e}", err=True)
        # Возвращаем fallback
        return {"type": "GET", "request": "/v1/assets", "_llm": "", "_source": "fallback"}, 0.0


@click.command()
@click.option(
    "--test-file",
    type=click.Path(exists=True, path_type=Path),
    default="data/processed/test.csv",
    help="Путь к test.csv",
)
@click.option(
    "--train-file",
    type=click.Path(exists=True, path_type=Path),
    default="data/processed/train.csv",
    help="Путь к train.csv",
)
@click.option(
    "--output-file",
    type=click.Path(path_type=Path),
    default="data/processed/submission.csv",
    help="Путь к submission.csv",
)
@click.option("--num-examples", type=int, default=10, help="Количество примеров для few-shot")
@click.option("--debug", is_flag=True, default=False, help="Печать детализированной статистики по train и топ ошибок")
@click.option("--errors-out", type=click.Path(path_type=Path), default=None, help="Сохранить ошибки в CSV")
@click.option("--force-llm", is_flag=True, default=False, help="Игнорировать детерминированный слой и всегда вызывать LLM")
def main(test_file: Path, train_file: Path, output_file: Path, num_examples: int, debug: bool, errors_out: Path | None, force_llm: bool) -> None:
    """Генерация submission.csv для хакатона"""
    from src.app.core.config import get_settings

    click.echo("🚀 Генерация submission файла...")
    click.echo(f"📖 Загрузка примеров из {train_file}...")

    # Получаем настройки для определения модели
    settings = get_settings()
    model = settings.openrouter_model

    # Загружаем примеры для few-shot
    examples = load_train_examples(train_file, num_examples)
    click.echo(f"✅ Загружено {len(examples)} примеров для few-shot learning")
    click.echo(f"🤖 Используется модель: {model}")

    # Читаем тестовый набор
    click.echo(f"📖 Чтение {test_file}...")
    test_questions = []
    with open(test_file, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            test_questions.append({"uid": row["uid"], "question": row["question"]})

    click.echo(f"✅ Найдено {len(test_questions)} вопросов для обработки")

    # Генерируем ответы
    click.echo("\n🤖 Генерация API запросов с помощью LLM...")
    results = []
    total_cost = 0.0

    # Используем tqdm с postfix для отображения стоимости
    progress_bar = tqdm(test_questions, desc="Обработка")
    for item in progress_bar:
        api_call, cost = generate_api_call(item["question"], examples, model, train_file, force_llm=force_llm)
        total_cost += cost
        results.append({
            "uid": item["uid"],
            "type": api_call["type"],
            "request": api_call["request"],
            "_llm": api_call.get("_llm", ""),
            "_source": api_call.get("_source", "")
        })

        # Обновляем postfix с текущей стоимостью
        progress_bar.set_postfix({"cost": f"${total_cost:.4f}"})

    # Записываем в submission.csv
    click.echo(f"\n💾 Сохранение результатов в {output_file}...")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["uid", "type", "request"],
            delimiter=";",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows([{k: r[k] for k in ("uid","type","request")} for r in results])

    click.echo(f"✅ Готово! Создано {len(results)} записей в {output_file}")
    click.echo(f"\n💰 Общая стоимость генерации: ${total_cost:.4f}")
    click.echo(f"   Средняя стоимость на запрос: ${total_cost / len(results):.6f}")
    click.echo("\n📊 Статистика по типам запросов:")
    type_counts: dict[str, int] = {}
    for r in results:
        type_counts[r["type"]] = type_counts.get(r["type"], 0) + 1
    for method, count in sorted(type_counts.items()):
        click.echo(f"  {method}: {count}")
    # source stats
    src_counts: dict[str, int] = {}
    for r in results:
        src = r.get("_source", "")
        if src:
            src_counts[src] = src_counts.get(src, 0) + 1
    if src_counts:
        click.echo("\n🔎 Источник путей:")
        for s,c in sorted(src_counts.items()):
            click.echo(f"  {s}: {c}")

    # Optional debug evaluation when test_file is train_file
    if debug:
        click.echo("\n🔎 Debug: сравнение с train и разбор ошибок")
        # Load truth
        truth: dict[str, dict[str, str]] = {}
        def _normalize_path(s: str) -> str:
            s = (s or "").strip()
            U = s.upper()
            for m in ("GET ", "POST ", "DELETE ", "PUT ", "PATCH "):
                if U.startswith(m):
                    return s[len(m):].strip()
            return s
        with open(train_file, encoding="utf-8") as f:
            rdr = csv.DictReader(f, delimiter=';')
            for row in rdr:
                # normalize request in truth: some rows have METHOD duplicated in request
                row_norm = dict(row)
                row_norm['request'] = _normalize_path(row.get('request',''))
                truth[row['uid']] = row_norm
        reg = EndpointRegistry()
        total = len(results)
        exact = 0
        type_ok = 0
        by_schema: dict[str, dict[str,int]] = {}
        errors: list[dict[str,str]] = []
        for r in results:
            uid = r['uid']
            pred_t, pred_p = r['type'], r['request']
            t = truth.get(uid, {})
            true_t, true_p = t.get('type',''), t.get('request','')
            schema = reg.classify_path(true_p) or 'other'
            rec = by_schema.setdefault(schema, {"total":0,"exact":0})
            rec["total"] += 1
            if pred_t == true_t:
                type_ok += 1
            if pred_t == true_t and pred_p == true_p:
                exact += 1
                rec["exact"] += 1
            else:
                errors.append({
                    "uid": uid,
                    "question": truth.get(uid, {}).get('question',''),
                    "true_type": true_t,
                    "true_request": true_p,
                    "pred_type": pred_t,
                    "pred_request": pred_p,
                    "schema": schema,
                    "llm": r.get('_llm',''),
                    "source": r.get('_source','')
                })
        click.echo(f"Total: {total}")
        click.echo(f"Exact matches: {exact}")
        click.echo(f"Type matches: {type_ok}")
        click.echo(f"Mismatches: {len(errors)}")
        click.echo("Per‑schema accuracy:")
        for sc,m in by_schema.items():
            acc = (m.get('exact',0)/max(1,m.get('total',0)))*100
            click.echo(f"  {sc}: {m.get('exact',0)}/{m.get('total',0)} = {acc:.1f}%")
        # Show top 20 errors
        for e in errors[:20]:
            click.echo(f"- [{e['schema']}] Q: {e['question']}\n  true: {e['true_type']} {e['true_request']}\n  pred: {e['pred_type']} {e['pred_request']}\n  llm: {e['llm'][:200]}")
        if errors_out:
            with open(errors_out, 'w', encoding='utf-8', newline='') as f:
                w = csv.DictWriter(f, fieldnames=list(errors[0].keys()) if errors else ['uid','question','true_type','true_request','pred_type','pred_request','schema','llm'])
                w.writeheader()
                w.writerows(errors)
            click.echo(f"📝 Ошибки сохранены в {errors_out}")


if __name__ == "__main__":
    main()
