from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List
import re as _re

from src.app.orchestration.extractor import extract_structured
from src.app.orchestration.endpoints import build_from_schema
from src.app.registry.endpoints import EndpointRegistry
from src.app.core.normalize import normalize_timeframe, normalize_iso8601, infer_market_symbol, parse_date_range
from src.app.core.symbols import SymbolResolver


def offline_map(question: str, context: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, str]]:
    """Deterministic NL -> (METHOD, PATH) using registry-driven heuristics (no LLM).

    Returns (method, path) or None if cannot map.
    """
    # 1) Try structured extractor
    schema, missing = extract_structured(question, context)
    if schema and not missing:
        method, path, params = build_from_schema(schema)
        # Inline query string for GET
        if method == "GET" and params:
            if "json" in params:
                params = {k: v for k, v in params.items() if k != "json"}
            if params:
                query = "&".join(f"{k}={v}" for k, v in params.items())
                if "?" in path:
                    path = f"{path}&{query}"
                else:
                    path = f"{path}?{query}"
        return method, path

    # 2) Registry-driven synonyms matching to guess schema and slots from context only
    reg = EndpointRegistry()
    import yaml as _yaml  # type: ignore
    with open(reg.config_path, encoding="utf-8") as f:
        cfg = _yaml.safe_load(f)
    items: List[dict] = cfg.get("endpoints", [])
    q = (question or "").lower()
    best: Optional[str] = None
    for it in items:
        syns = [s.lower() for s in (it.get("synonyms") or [])]
        if any(s in q for s in syns):
            best = it.get("schema")
            break
    if not best:
        return None

    ctx = dict(context or {})
    # Use shared resolver for symbol if available in text
    if "symbol" not in ctx:
        sym = SymbolResolver().resolve(question, ctx, allow_llm=False)
        if sym:
            ctx["symbol"] = sym
    # Heuristic slot completion: symbol + timeframe/dates
    try:
        param_names: set[str] = set()
        for ep in items:
            params = ep.get("params") or {}
            if isinstance(params, dict):
                for k in params.keys():
                    param_names.add(str(k))
    except Exception:
        param_names = set()

    # Try to infer symbol from question text if missing
    def _infer_symbol_from_text(text: str) -> Optional[str]:
        if not text:
            return None
        # Find tokens like SBER or SBER@MISX
        candidates = _re.findall(r"\b[A-Z]{3,6}(?:@[A-Z]{2,6})?\b", text.upper())
        if not candidates:
            return None
        return infer_market_symbol(candidates[0])

    if "symbol" in param_names or "{symbol}" in str(items):
        sym = ctx.get("symbol") or _infer_symbol_from_text(question)
        if sym:
            ctx["symbol"] = infer_market_symbol(sym)
    if "timeframe" in param_names:
        if ctx.get("timeframe"):
            ctx["timeframe"] = normalize_timeframe(ctx["timeframe"])  # type: ignore[index]
    for key in ("start", "end"):
        if ctx.get(key):
            ctx[key] = normalize_iso8601(str(ctx[key]))

    # Build schema instance generically using registry-required slots
    from src.app.schemas import requests as req_schemas
    schema_cls = getattr(req_schemas, best, None)
    if schema_cls is None:
        return None
    required = set(reg.required_slots(best))

    if "timeframe" in required and not ctx.get("timeframe"):
        ctx["timeframe"] = normalize_timeframe("D")
    if ("start" in required or "end" in required) and (not ctx.get("start") or not ctx.get("end")):
        rng = parse_date_range(question)
        if rng:
            s, e = rng
            ctx.setdefault("start", s)
            ctx.setdefault("end", e)

    kwargs: Dict[str, Any] = {}
    for field_name in getattr(schema_cls, "model_fields", {}).keys():
        if field_name in ctx and ctx[field_name] is not None:
            kwargs[field_name] = ctx[field_name]
        elif field_name in required:
            kwargs[field_name] = "{" + field_name + "}"
    try:
        candidate = schema_cls(**kwargs)
    except Exception:
        return None

    method, path, params = build_from_schema(candidate)
    if method == "GET" and params:
        if "json" in params:
            params = {k: v for k, v in params.items() if k != "json"}
        if params:
            query = "&".join(f"{k}={v}" for k, v in params.items())
            if "?" in path:
                path = f"{path}&{query}"
            else:
                path = f"{path}?{query}"
    return method, path



