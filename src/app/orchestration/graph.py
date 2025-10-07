from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.app.core.normalize import normalize_timeframe, infer_market_symbol, normalize_iso8601
from datetime import datetime, timezone, timedelta
from src.app.core.parsing import extract_api_request
from src.app.orchestration.router import ToolRequest, ToolRouter
from src.app.orchestration.types import OrchestrationContext, OrchestrationResult
from src.app.core.safety import build_order_summary, sanity_checks
from src.app.orchestration.utils import find_placeholders, substitute_placeholders
from src.app.orchestration.extractor import extract_structured, extract_structured_llm
from src.app.orchestration.endpoints import build_from_schema
from src.app.core.prompting import disambiguation_prompt
from src.app.core.policy import load_policy, evaluate_policy
from src.app.core.audit import get_audit_logger
from src.app.core.otel import get_tracer, init_tracer
from src.app.core.security import generate_intent_hash, check_and_remember_idempotency
from src.app.core.wise_orders import compute_market_insights, suggest_from_insights, extract_symbol_from_text


@dataclass
class PlannerOutput:
    needs_disambiguation: bool
    method: Optional[str]
    path: Optional[str]
    message: Optional[str] = None


class SimplePlanner:
    """Minimal planner: expects assistant to emit API_REQUEST line.

    If absent, signals disambiguation. No hardcoding of endpoints.
    """

    def plan(self, assistant_text: str) -> PlannerOutput:
        method, path = extract_api_request(assistant_text)
        if not method or not path:
            return PlannerOutput(needs_disambiguation=True, method=None, path=None, message="Требуются уточнения параметров")
        return PlannerOutput(needs_disambiguation=False, method=method, path=path)


class ParameterExtractor:
    """Placeholder extractor for future structured argument extraction.

    Contains normalization helpers (e.g., timeframe). Avoids hardcoded cases.
    """

    @staticmethod
    def normalize_timeframe_value(value: str) -> str:
        return normalize_timeframe(value)

    @staticmethod
    def fill_path_placeholders(path: str, ctx: OrchestrationContext) -> OrchestrationResult | str:
        placeholders = find_placeholders(path)
        if not placeholders:
            return path
        params = {}
        if ctx.account_id:
            params["account_id"] = ctx.account_id
        new_path, missing = substitute_placeholders(path, params)  # do not guess missing
        if missing:
            return OrchestrationResult(
                disambiguation=True,
                message=f"Не хватает параметров: {', '.join(missing)}",
                api={"method": None, "path": path},
            )
        return new_path

    @staticmethod
    def normalize_symbols_in_path(path: str) -> str:
        """Ensure instrument symbols contain MIC and enrich bars endpoint with defaults.

        - /v1/instruments/{symbol}/... → symbol := infer_market_symbol(symbol)
        - Normalize singular '/bar' to '/bars'
        - For /bars normalize query: prefer timeframe+interval.start_time/end_time;
          if found legacy params (interval=, from=, to=) — convert to canonical and drop duplicates
        """
        try:
            base, sep, query = path.partition("?")
            parts = base.strip("/").split("/")
            changed = False
            # Fix singular '/bar' → '/bars'
            if parts and parts[-1] == "bar":
                parts[-1] = "bars"
                changed = True
            # Normalize MIC
            if "instruments" in parts:
                idx = parts.index("instruments")
                if idx + 1 < len(parts):
                    symbol = parts[idx + 1]
                    fixed = infer_market_symbol(symbol)
                    if fixed != symbol:
                        parts[idx + 1] = fixed
                        changed = True
            base = "/" + "/".join(parts) if changed else base

            # Normalize /bars params
            is_bars = base.endswith("/bars") or "/bars/" in base
            if is_bars:
                q = query or ""
                # If legacy params used, convert to canonical
                # interval=1d|5m -> timeframe=TIME_FRAME_*
                # from=YYYY-MM-DD [& to=YYYY-MM-DD] -> interval.start_time / interval.end_time ISO
                import re as _re
                params_pairs = []
                if q:
                    for part in q.split("&"):
                        if part:
                            kv = part.split("=", 1)
                            if len(kv) == 2:
                                params_pairs.append((kv[0], kv[1]))
                pmap = {k: v for k, v in params_pairs}
                canonical = {}
                # timeframe
                if "timeframe" in pmap:
                    canonical["timeframe"] = pmap["timeframe"]
                elif "interval" in pmap:
                    iv = pmap["interval"].lower()
                    tf_map = {"1d": "TIME_FRAME_D", "1w": "TIME_FRAME_W", "1mn": "TIME_FRAME_MN",
                              "1m": "TIME_FRAME_M1", "5m": "TIME_FRAME_M5", "15m": "TIME_FRAME_M15",
                              "30m": "TIME_FRAME_M30", "1h": "TIME_FRAME_H1", "4h": "TIME_FRAME_H4"}
                    canonical["timeframe"] = tf_map.get(iv, "TIME_FRAME_D")
                else:
                    canonical["timeframe"] = "TIME_FRAME_D"
                # interval start/end
                if "interval.start_time" in pmap or "interval.end_time" in pmap:
                    if "interval.start_time" in pmap:
                        canonical["interval.start_time"] = pmap["interval.start_time"]
                    if "interval.end_time" in pmap:
                        canonical["interval.end_time"] = pmap["interval.end_time"]
                else:
                    # from/to fallback
                    start_iso = None
                    end_iso = None
                    if "from" in pmap:
                        try:
                            start_iso = normalize_iso8601(pmap["from"])  # YYYY-MM-DD or NL
                        except Exception:
                            start_iso = None
                    if "to" in pmap:
                        try:
                            end_iso = normalize_iso8601(pmap["to"])  # YYYY-MM-DD or NL
                        except Exception:
                            end_iso = None
                    if not start_iso or not end_iso:
                        now = datetime.now(timezone.utc)
                        if not start_iso:
                            start_iso = (now - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
                        if not end_iso:
                            end_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                    canonical["interval.start_time"] = start_iso
                    canonical["interval.end_time"] = end_iso
                # rebuild query canonical
                query = "&".join([
                    f"timeframe={canonical['timeframe']}",
                    f"interval.start_time={canonical['interval.start_time']}",
                    f"interval.end_time={canonical['interval.end_time']}"
                ])
                sep = "?"

            return base + (sep + query if query else "")
        except Exception:
            return path


def execute_graph(
    assistant_text: str,
    router: ToolRouter,
    ctx: OrchestrationContext,
) -> OrchestrationResult:
    import time as _t
    init_tracer()
    tracer = get_tracer()
    trace: list[dict[str, Any]] = []
    t0 = _t.perf_counter()
    with tracer.start_as_current_span("plan"):
        planner = SimplePlanner()
        plan = planner.plan(assistant_text)
    trace.append({"stage": "plan", "dt_ms": int((_t.perf_counter() - t0) * 1000)})
    if plan.needs_disambiguation:
        return OrchestrationResult(disambiguation=True, message=plan.message, trace=trace)

    # If planner did not yield METHOD/PATH, try structured extraction
    t1 = _t.perf_counter()
    if not (plan.method and plan.path):
        with tracer.start_as_current_span("extract"):
            schema, missing = extract_structured(assistant_text)
            if not schema and not missing:
                # Try LLM-backed extraction
                schema, missing = extract_structured_llm(assistant_text)
            if missing:
                trace.append({"stage": "extract_missing", "dt_ms": int((_t.perf_counter() - t1) * 1000), "missing": missing})
                return OrchestrationResult(disambiguation=True, message=disambiguation_prompt(missing), trace=trace)
            if schema:
                method, path, params = build_from_schema(schema)
                plan.method, plan.path = method, path
    assert plan.method and plan.path
    trace.append({"stage": "extract", "dt_ms": int((_t.perf_counter() - t1) * 1000)})

    # Extract/normalize parameters for placeholders
    t2 = _t.perf_counter()
    with tracer.start_as_current_span("placeholders"):
        extractor = ParameterExtractor()
        filled = extractor.fill_path_placeholders(plan.path, ctx)
    if isinstance(filled, OrchestrationResult):
        filled.trace = (filled.trace or []) + trace
        return filled
    plan.path = extractor.normalize_symbols_in_path(filled)
    trace.append({"stage": "placeholders", "dt_ms": int((_t.perf_counter() - t2) * 1000)})

    # Safety gate for POST/DELETE
    policy = load_policy()
    logger = get_audit_logger()
    with tracer.start_as_current_span("safety"):
        allowed, requires_confirm, reasons = evaluate_policy(plan.method, plan.path, None, policy)
    if not allowed:
        logger.log_safety(plan.method, plan.path, decision="blocked", reasons=reasons, context={"phase": "pre-exec"})
        return OrchestrationResult(error="Политика безопасности", message=", ".join(reasons), api={"method": plan.method, "path": plan.path}, trace=trace)
    if requires_confirm and not ctx.confirm:
        import os as _os

        logger.log_safety(plan.method, plan.path, decision="needs_confirm", reasons=["confirm_required"], context={"phase": "pre-exec"})
        intent_hash = generate_intent_hash(plan.method, plan.path)
        ttl = int(_os.getenv("CONFIRM_TTL_SECONDS", "60"))
        return OrchestrationResult(
            requires_confirmation=True,
            api={"method": plan.method, "path": plan.path},
            message=f"Требуется подтверждение (TTL≈{ttl}с). intent={intent_hash[:8]}",
            trace=trace,
        )

    if ctx.dry_run:
        return OrchestrationResult(api={"method": plan.method, "path": plan.path}, data={"dry_run": True}, trace=trace)

    # Execute
    t3 = _t.perf_counter()
    with tracer.start_as_current_span("execute"):
        # Idempotency guard for POST/DELETE
        if plan.method in ("POST", "DELETE"):
            key = generate_intent_hash(plan.method, plan.path)
            if not check_and_remember_idempotency(key):
                return OrchestrationResult(error="Повтор операции заблокирован идемпотентностью", api={"method": plan.method, "path": plan.path}, trace=trace)
        # Best-effort build JSON for order creation if missing
        kwargs: Dict[str, Any] = {}
        try:
            if plan.method == "POST" and plan.path.endswith("/orders"):
                import re as _re
                txt = assistant_text.lower()
                # Extract intent generically
                side = "buy" if any(w in txt for w in ["куп", "buy"]) else ("sell" if any(w in txt for w in ["прод", "sell"]) else None)
                explicit_type = "limit" if any(w in txt for w in ["лимит", "limit"]) else ("market" if any(w in txt for w in ["рынок", "market"]) else None)
                tif = "DAY" if any(w in txt for w in ["day", "день", "сегодня"]) else None
                q_m = _re.search(r"(\d+)\s*лот\w*", txt)
                qty = int(q_m.group(1)) if q_m else None
                p_m = _re.search(r"по\s*(\d+[\.,]?\d*)", txt)
                price = float(p_m.group(1).replace(",", ".")) if p_m else None
                sym = extract_symbol_from_text(plan.path) or extract_symbol_from_text(assistant_text)
                if sym and "@" not in sym:
                    try:
                        from src.app.core.normalize import infer_market_symbol as _infer_market_symbol
                        sym = _infer_market_symbol(sym)
                    except Exception:
                        pass
                # Determine order_type by presence of keywords and price
                order_type: Optional[str] = None
                if explicit_type == "market" and price is None:
                    order_type = "market"
                elif price is not None:
                    order_type = "limit"
                elif explicit_type == "limit":
                    order_type = None  # need price; skip building body
                else:
                    order_type = None
                if sym and side and qty and (order_type == "market" or (order_type == "limit" and price is not None)):
                    side_out = "BUY" if side == "buy" else ("SELL" if side == "sell" else side.upper())
                    type_out = "MARKET" if (order_type or "market") == "market" else "LIMIT"
                    tif_out = (tif or "DAY").upper()
                    payload: Dict[str, Any] = {
                        "symbol": sym,
                        "side": side_out,
                        "order_type": type_out,
                        "quantity": qty,
                        "time_in_force": tif_out,
                    }
                    if type_out == "LIMIT" and price is not None:
                        payload["price"] = price
                    kwargs["json"] = payload
        except Exception:
            pass
        response = router.execute(ToolRequest(method=plan.method, path=plan.path), **kwargs)
        # Generic fallback for order creation shape if 400 Bad Request
        try:
            if (
                plan.method == "POST"
                and plan.path.endswith("/orders")
                and isinstance(response, dict)
                and str(response.get("status_code") or "").strip() in ("400",)
            ):
                attempts: list[dict[str, Any]] = []
                if "json" in kwargs:
                    attempts.append({"shape": "flat", "json": kwargs.get("json")})
                # Build nested shape if not already
                if not (isinstance(kwargs.get("json"), dict) and "order" in kwargs.get("json", {})):
                    flat = kwargs.get("json") or {}
                    if isinstance(flat, dict):
                        sym_f = flat.get("symbol") or flat.get("instrument")
                        side_f = flat.get("side")
                        type_f = flat.get("order_type") or flat.get("type")
                        qty_f = flat.get("quantity") or flat.get("qty") or flat.get("lots")
                        tif_f = flat.get("time_in_force") or flat.get("tif")
                        price_f = flat.get("price") or flat.get("limit_price")
                        order_obj: Dict[str, Any] = {
                            "instrument": sym_f,
                            "side": (side_f.lower() if isinstance(side_f, str) else side_f),
                            "type": (type_f.lower() if isinstance(type_f, str) else type_f),
                            "quantity": qty_f,
                        }
                        if tif_f:
                            order_obj["time_in_force"] = tif_f
                        if price_f is not None:
                            order_obj["price"] = price_f
                        nested = {"order": {k: v for k, v in order_obj.items() if v is not None}}
                        second = router.execute(ToolRequest(method=plan.method, path=plan.path), json=nested)
                        attempts.append({"shape": "nested", "json": nested, "result_error": isinstance(second, dict) and second.get("error")})
                        # If fallback succeeded, replace response
                        if not (isinstance(second, dict) and second.get("error")):
                            response = second
                        else:
                            # Attach attempts for diagnostics
                            if not isinstance(response, dict):
                                response = {"raw": response}
                            response["order_attempts"] = attempts
        except Exception:
            pass
        # Post-verify for order creation: if API returns empty, fetch active orders for context
        try:
            if plan.method == "POST" and plan.path.endswith("/orders"):
                acct = ctx.account_id
                if acct:
                    orders_path = f"/v1/accounts/{acct}/orders"
                    orders_resp = router.execute(ToolRequest(method="GET", path=orders_path))
                    # Attach verification context without assuming exact schema
                    info: Dict[str, Any] = {"orders_path": orders_path}
                    if isinstance(orders_resp, list):
                        info["active_orders_count"] = len(orders_resp)
                    elif isinstance(orders_resp, dict):
                        lst = None
                        for k in ("orders", "items", "data", "result"):
                            v = orders_resp.get(k)
                            if isinstance(v, list):
                                lst = v
                                break
                        if isinstance(lst, list):
                            info["active_orders_count"] = len(lst)
                        else:
                            info["active_orders_preview"] = str(orders_resp)[:500]
                    # Ensure response is a dict so chat layer can show both
                    if not isinstance(response, dict):
                        response = {"raw": response}
                    response["post_verify"] = info
        except Exception:
            pass
    logger.log_safety(plan.method, plan.path, decision="executed", reasons=[], context={"phase": "post-exec"})
    trace.append({"stage": "execute", "dt_ms": int((_t.perf_counter() - t3) * 1000)})

    # Order safety post-check (best-effort; non-blocking)
    if plan.method == "POST" and isinstance(response, dict) and "order" in str(response).lower():
        summary = build_order_summary({})
        _ = sanity_checks(summary)

    # Wise Orders: compute insights and suggestions when symbol is present
    insights = None
    suggestions = None
    try:
        sym = extract_symbol_from_text(plan.path) or extract_symbol_from_text(assistant_text)
        if sym:
            insights = compute_market_insights(router, sym)
            suggestions = suggest_from_insights(insights)
    except Exception:
        pass

    return OrchestrationResult(api={"method": plan.method, "path": plan.path}, data=response, insights=insights, suggestions=suggestions, trace=trace)


