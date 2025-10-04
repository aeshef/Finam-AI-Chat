from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, Union, List, Type

from src.app.core.normalize import normalize_timeframe, normalize_iso8601, infer_market_symbol, parse_date_range
from src.app.core.symbols import SymbolResolver, SymbolResolutionConfig
from src.app.schemas import requests as req_schemas
from src.app.schemas.requests import (
    AccountRequest,
    BarsRequest,
    OrdersListRequest,
    OrderbookRequest,
    QuoteRequest,
    TradesLatestRequest,
    OrderGetRequest,
    TransactionsRequest,
    TradesRequest,
    OrderCancelRequest,
    AssetsListRequest,
    ExchangesListRequest,
    AssetInfoRequest,
    AssetParamsRequest,
    AssetScheduleRequest,
    AssetOptionsRequest,
)
from src.app.core.prompting import extraction_prompt
from src.app.registry.endpoints import EndpointRegistry
from src.app.core.llm import call_llm


Extracted = Union[
    QuoteRequest,
    OrderbookRequest,
    BarsRequest,
    TradesLatestRequest,
    AccountRequest,
    OrdersListRequest,
    OrderGetRequest,
    TradesRequest,
    TransactionsRequest,
    OrderCancelRequest,
    AssetsListRequest,
    ExchangesListRequest,
    AssetInfoRequest,
    AssetParamsRequest,
    AssetScheduleRequest,
    AssetOptionsRequest,
]


def extract_structured(question: str, context: Optional[Dict[str, Any]] = None) -> Tuple[Optional[Extracted], list[str]]:
    """Registry-driven heuristic extractor using endpoint intents and synonyms.

    Returns (schema, missing_fields). When missing_fields non-empty, caller should disambiguate.
    """
    q = (question or "").lower()
    ctx = context or {}
    reg = EndpointRegistry()

    # Load intents/synonyms from registry YAML
    import yaml as _yaml  # type: ignore
    with open(reg.config_path, encoding="utf-8") as f:
        cfg = _yaml.safe_load(f)
    items: List[dict] = cfg.get("endpoints", [])

    # Utilities available to intent matcher and later construction
    import re as _re

    def _infer_order_id(text: str) -> Optional[str]:
        # Accept broad Finam-style order ids, e.g., ORD123, ORDERR01, ORD-ABC-123
        m = _re.search(r"\bORD[A-Z0-9-]*\b", text.upper())
        return m.group(0) if m else None

    def _infer_account_id(text: str) -> Optional[str]:
        m = _re.search(r"\b(?:ACC|USR|FIN)-\d{3}-[A-Z]\b", text.upper())
        if m:
            return m.group(0)
        m2 = _re.search(r"\b[A-Z]\d{5,}\b", text.upper())
        if m2:
            return m2.group(0)
        m3 = _re.search(r"\b\d{3,}\b", text)
        if m3:
            return m3.group(0)
        return None

    sym_resolver = SymbolResolver()

    def match_intent() -> Optional[str]:
        # Score-based selection: synonyms hits + slot availability boosts
        best_schema: Optional[str] = None
        best_score = 0
        for it in items:
            score = 0
            syns = [s.lower() for s in (it.get("synonyms") or [])]
            # Weight synonyms higher than generic boosts
            score += 2 * sum(1 for s in syns if s and s in q)
            kws = [k.lower() for k in (it.get("keywords") or [])]
            score += sum(1 for k in kws if k and k in q)
            path_tpl = str(it.get("path") or "")
            # Boost if symbol present and endpoint uses symbol
            if ("{symbol}" in path_tpl or "/instruments/" in path_tpl or "/assets/" in path_tpl):
                # quick symbol presence heuristic
                if sym_resolver.resolve(question, ctx, allow_llm=False):
                    score += 1
            # Boost if account present and endpoint uses account
            if ("{account_id}" in path_tpl or "/accounts/" in path_tpl) and (_infer_account_id(question) or ctx.get("account_id")):
                score += 1
            # Strong hint from question formatting
            if question.strip().lower().startswith("delete") or "отмен" in q:
                if it.get("method", "").upper() == "DELETE":
                    score += 2
            # Boost if order id present and endpoint is order-specific path
            if ("/orders/" in path_tpl and "{order_id}" in path_tpl) and _infer_order_id(question):
                score += 2
            # Nudge for specific resource paths
            if "/schedule" in path_tpl and ("расписан" in q or "клиринг" in q):
                score += 1
            if "/params" in path_tpl and ("параметр" in q or "шаг цены" in q or "лот" in q or "ставка риска" in q or "ГО" in q):
                score += 1
            if score > best_score:
                best_score = score
                best_schema = it.get("schema")
        return best_schema

    schema_name = match_intent()
    if not schema_name:
        return None, []

    def _infer_symbol_from_text(text: str) -> Optional[str]:
        if not text:
            return None
        # 1) direct ticker pattern
        candidates = _re.findall(r"\b[A-Z0-9]{2,8}(?:@[A-Z]{2,6})?\b", text.upper())
        if candidates:
            return infer_market_symbol(candidates[0])
        # 2) alias keywords in russian text
        try:
            import yaml as _yaml  # type: ignore
            from pathlib import Path as _Path
            alias_path = _Path("configs/aliases.yaml")
            if alias_path.exists():
                with open(alias_path, encoding="utf-8") as _f:
                    _cfg = _yaml.safe_load(_f) or {}
                aliases = {k.lower(): v for k, v in (_cfg.get("instrument_aliases") or {}).items()}
                low = text.lower()
                for key, ticker in aliases.items():
                    if key in low:
                        return infer_market_symbol(ticker)
        except Exception:
            pass
        return None

    # Build kwargs for schema based on available context with graceful fallbacks
    # Use pluggable symbol resolver (pattern -> aliases -> optional local/LLM)
    sym_resolver = SymbolResolver()
    sym = sym_resolver.resolve(question, ctx, allow_llm=False) or _infer_symbol_from_text(question)
    acc = ctx.get("account_id") or _infer_account_id(question)
    order_id = ctx.get("order_id") or _infer_order_id(question)

    tf_raw = ctx.get("timeframe")
    timeframe = normalize_timeframe(tf_raw) if tf_raw else normalize_timeframe("D")
    # Boost timeframe based on language cues
    if not tf_raw:
        if any(k in q for k in ["днев", "day", "день"]):
            timeframe = normalize_timeframe("D")
        elif any(k in q for k in ["час", "h1", "часовой"]):
            timeframe = normalize_timeframe("H1")

    start = ctx.get("start")
    end = ctx.get("end")
    if start:
        start = normalize_iso8601(str(start))
    if end:
        end = normalize_iso8601(str(end))
    # If target schema supports start/end but none provided, try parse_date_range from question
    if (start is None or end is None) and schema_name in {"BarsRequest", "TradesRequest", "TransactionsRequest"}:
        rng = parse_date_range(question)
        if rng:
            s, e = rng
            if start is None:
                start = s
            if end is None:
                end = e

    # Instantiate schema dynamically using its name
    schema_cls: Optional[Type[Any]] = getattr(req_schemas, schema_name, None)  # type: ignore[attr-defined]
    if schema_cls is None:
        return None, []

    # Prepare constructor arguments by inspecting model fields and registry-required slots
    required_slots = reg.required_slots(schema_name)
    model_fields = getattr(schema_cls, "model_fields", {})
    kwargs: Dict[str, Any] = {}
    for field_name in model_fields.keys():
        if field_name == "symbol":
            if sym:
                kwargs[field_name] = sym
            else:
                # Leave symbol missing -> this schema likely cannot be built
                pass
        elif field_name == "account_id":
            # Provide placeholder only if required by template; otherwise include if available
            if "account_id" in required_slots:
                kwargs[field_name] = acc or "{account_id}"
            elif acc:
                kwargs[field_name] = acc
        elif field_name == "order_id":
            if "order_id" in required_slots:
                kwargs[field_name] = order_id or "{order_id}"
            elif order_id:
                kwargs[field_name] = order_id
        elif field_name == "timeframe":
            kwargs[field_name] = timeframe
        elif field_name == "start":
            if start is not None:
                kwargs[field_name] = start
        elif field_name == "end":
            if end is not None:
                kwargs[field_name] = end
        elif field_name == "limit":
            if "limit" in ctx:
                kwargs[field_name] = ctx["limit"]
        # leave other optional fields as defaults

    try:
        instance = schema_cls(**kwargs)
    except Exception:
        # If we could not construct due to missing required fields (e.g., symbol), report missing
        missing: list[str] = []
        for name, info in getattr(schema_cls, "model_fields", {}).items():
            if getattr(info, "is_required", False) and name not in kwargs:
                missing.append(name)
        return None, missing

    return instance, []


def extract_structured_llm(question: str) -> Tuple[Optional[Extracted], list[str]]:
    """LLM-backed JSON extraction with minimal post-validation into Pydantic schemas."""
    prompt = extraction_prompt() + "\n\nВопрос: \"" + question + "\"\nJSON:"
    messages = [{"role": "user", "content": prompt}]
    try:
        resp = call_llm(messages, temperature=0.0, max_tokens=300)
        content = resp["choices"][0]["message"]["content"]
        # Trust model to output JSON; fallback silently if not
        import json as _json

        data = _json.loads(content)
        intent = (data.get("intent") or "").lower()
        missing: list[str] = []

        if intent == "quote":
            sym = data.get("symbol")
            if not sym:
                return None, ["symbol"]
            return QuoteRequest(symbol=infer_market_symbol(sym)), []

        if intent == "bars":
            sym = data.get("symbol")
            if not sym:
                return None, ["symbol"]
            tf = normalize_timeframe(data.get("timeframe", "D"))
            start = data.get("start")
            end = data.get("end")
            if start:
                start = normalize_iso8601(str(start))
            if end:
                end = normalize_iso8601(str(end))
            return BarsRequest(symbol=infer_market_symbol(sym), timeframe=tf, start=start, end=end), []

        if intent == "orders_list":
            acc = data.get("account_id")
            if not acc:
                return None, ["account_id"]
            return OrdersListRequest(account_id=acc), []

        if intent == "account":
            acc = data.get("account_id")
            if not acc:
                return None, ["account_id"]
            return AccountRequest(account_id=acc), []

        return None, missing
    except Exception:
        return None, []


