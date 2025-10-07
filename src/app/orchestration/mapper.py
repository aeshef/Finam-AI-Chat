from __future__ import annotations

from pathlib import Path
from typing import Any, Tuple
import os
from datetime import datetime, timezone

from src.app.core.llm import call_llm
from src.app.core.prompting import system_prompt_for_mapping, endpoints_spec, symbols_spec
from src.app.registry.endpoints import EndpointRegistry
from src.app.orchestration.endpoints import build_from_schema
from src.app.orchestration.extractor import extract_structured
from src.app.adapters.finam_client import FinamAPIClient
from src.app.core.normalize import parse_date_range


def _collect_symbols_from_train(train_file: Path) -> list[str]:
    import csv, re

    tokens: set[str] = set()
    with open(train_file, encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            q = (row.get("question") or "")
            for tok in re.findall(r"\b[A-Z0-9]{2,12}(?:@[A-Z]{2,8})?\b", q.upper()):
                if tok.startswith("ORD"):
                    continue
                if tok.isdigit():
                    continue
                tokens.add(tok)
    return list(tokens)


def create_prompt(question: str, train_file: Path) -> str:
    return (
        system_prompt_for_mapping()
        + "\n\n"
        + endpoints_spec()
        + "\n\n"
        + symbols_spec(_collect_symbols_from_train(train_file))
        + "\n\nВопрос: \"" + question + "\"\nОтвет (только HTTP метод и путь, без объяснений):"
    )


def parse_llm_response(response: str) -> Tuple[str, str]:
    response = response.strip()
    methods = ["GET", "POST", "DELETE", "PUT", "PATCH"]
    method = "GET"
    request = response
    for m in methods:
        if response.upper().startswith(m):
            method = m
            request = response[len(m):].strip()
            break
    if not request.startswith("/"):
        parts = request.split()
        for part in parts:
            if part.startswith("/"):
                request = part
                break
    if not request.startswith("/"):
        request = "/v1/assets"
    return method, request


def generate_api_call(question: str, model: str, train_file: Path, force_llm: bool = False) -> tuple[dict[str, Any], float]:
    # Deterministic layer unless forced
    if not force_llm:
        schema, missing = extract_structured(question)
        if schema and not missing:
            method, path, params = build_from_schema(schema)
            if params and method == "GET" and path and "?" not in path:
                query = "&".join(f"{k}={v}" for k, v in params.items())
                path = f"{path}?{query}"
            return {"type": method, "request": path, "_source": "structured"}, 0.0

    # LLM layer with catalog grounding
    prompt = create_prompt(question, train_file)
    messages = [{"role": "user", "content": prompt}]
    try:
        response = call_llm(messages, temperature=0.0, max_tokens=200)
        llm_answer = response["choices"][0]["message"]["content"].strip()
        method, request = parse_llm_response(llm_answer)
        # Validate and fallback
        reg = EndpointRegistry()
        if not request.startswith("/") or reg.classify_path(request) is None:
            from src.app.leaderboard.offline_map import offline_map
            mapped = offline_map(question)
            if mapped:
                method, request = mapped
        usage = response.get("usage", {})
        # simplistic cost: leave 0.0 if not provided by backend
        cost = 0.0
        return {"type": method, "request": request, "_llm": llm_answer, "_source": "llm"}, cost
    except Exception:
        return {"type": "GET", "request": "/v1/assets", "_source": "fallback"}, 0.0


def map_and_execute(
    question: str,
    account_id: str | None,
    model: str,
    train_file: Path,
    force_llm: bool = False,
    api_token: str | None = None,
) -> dict[str, Any]:
    """Map NL→(METHOD, PATH) and execute via FinamAPIClient. Returns dict with mapping and API response."""
    mapped, _ = generate_api_call(question, model=model, train_file=train_file, force_llm=force_llm)
    method = mapped.get("type", "GET")
    path = mapped.get("request", "/v1/assets")
    # Default account id from env if not provided
    if not account_id:
        account_id = os.getenv("DEFAULT_ACCOUNT_ID") or None
    if account_id and "{account_id}" in path:
        path = path.replace("{account_id}", account_id)
    # Clamp future end_time for interval placeholders if present
    if ("/bars" in path or "/trades" in path or "/transactions" in path) and "{slot}" in path:
        rng = parse_date_range(question)
        if rng:
            start, end = rng
            now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if end > now_iso:
                end = now_iso
            path = path.replace("interval.start_time={slot}", f"interval.start_time={start}")
            path = path.replace("interval.end_time={slot}", f"interval.end_time={end}")

    # If bars requested without explicit interval params, inject a safe default from question
    if "/bars" in path and "interval.start_time=" not in path:
        rng = parse_date_range(question)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if rng:
            start, end = rng
        else:
            # fallback: last 30 days
            from datetime import timedelta as _td
            start_dt = datetime.now(timezone.utc) - _td(days=30)
            start = start_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            end = now_iso
        if end > now_iso:
            end = now_iso
        sep = "&" if "?" in path else "?"
        path = f"{path}{sep}timeframe=TIME_FRAME_D&interval.start_time={start}&interval.end_time={end}"
    client = FinamAPIClient(access_token=api_token)
    api_response = client.execute_request(method, path)
    return {"type": method, "request": path, "response": api_response, "_source": mapped.get("_source", "")}

