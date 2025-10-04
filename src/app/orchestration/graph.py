from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.app.core.normalize import normalize_timeframe, infer_market_symbol
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
        - For /bars without params, add timeframe=D and last 7 days interval
        """
        try:
            base, sep, query = path.partition("?")
            parts = base.strip("/").split("/")
            changed = False
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

            # Enrich bars defaults
            is_bars = base.endswith("/bars") or "/bars/" in base
            if is_bars:
                q = query or ""
                need_tf = "timeframe=" not in q
                need_start = "interval.start_time=" not in q
                need_end = "interval.end_time=" not in q
                if need_tf or need_start or need_end:
                    params = []
                    if q:
                        params.append(q)
                    if need_tf:
                        params.append("timeframe=TIME_FRAME_D")
                    now = datetime.now(timezone.utc)
                    if need_start:
                        start = (now - timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
                        params.append(f"interval.start_time={start}")
                    if need_end:
                        end = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                        params.append(f"interval.end_time={end}")
                    query = "&".join([p for p in params if p])
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
        response = router.execute(ToolRequest(method=plan.method, path=plan.path))
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


