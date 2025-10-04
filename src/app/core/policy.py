from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SafetyPolicy:
    allowed_methods: List[str]
    confirm_methods: List[str]
    allowed_markets: List[str]
    max_order_quantity: int


def load_policy() -> SafetyPolicy:
    # Optional JSON policy via env path, else defaults
    path = os.getenv("APP_SAFETY_POLICY_JSON")
    if path and os.path.exists(path):
        try:
            data = json.loads(open(path, encoding="utf-8").read())
            return SafetyPolicy(
                allowed_methods=data.get("allowed_methods", ["GET", "POST", "DELETE"]),
                confirm_methods=data.get("confirm_methods", ["POST", "DELETE"]),
                allowed_markets=data.get("allowed_markets", ["MISX", "FORTS", "RTSX", "XNGS", "SPBEX"]),
                max_order_quantity=int(data.get("max_order_quantity", 10000)),
            )
        except Exception:
            pass
    return SafetyPolicy(
        allowed_methods=["GET", "POST", "DELETE"],
        confirm_methods=["POST", "DELETE"],
        allowed_markets=["MISX", "FORTS", "RTSX", "XNGS", "SPBEX"],
        max_order_quantity=10000,
    )


def evaluate_policy(method: str, path: str, request_kwargs: Optional[Dict[str, Any]], policy: SafetyPolicy) -> Tuple[bool, bool, List[str]]:
    """Return (allowed, requires_confirm, reasons). Generic checks only."""
    reasons: List[str] = []
    m = method.upper()
    if m not in policy.allowed_methods:
        reasons.append("Method not allowed")
        return False, False, reasons

    requires_confirm = m in set(policy.confirm_methods)

    # Market check (if symbol appears in path or JSON order instrument like SBER@MISX)
    market: Optional[str] = None
    try:
        import re

        sym_match = re.search(r"instruments/([^/]+)/", path)
        if sym_match:
            sym = sym_match.group(1)
            if "@" in sym:
                market = sym.split("@", 1)[1]
        if not market and request_kwargs and isinstance(request_kwargs.get("json"), dict):
            ins = request_kwargs["json"].get("instrument")
            if isinstance(ins, str) and "@" in ins:
                market = ins.split("@", 1)[1]
    except Exception:
        pass
    if market and market not in policy.allowed_markets:
        reasons.append(f"Market {market} not in allowlist")

    # Quantity check for order create
    if m == "POST" and request_kwargs and isinstance(request_kwargs.get("json"), dict):
        qty = request_kwargs["json"].get("quantity")
        try:
            if qty is not None and int(qty) > policy.max_order_quantity:
                reasons.append("Order quantity exceeds max policy limit")
        except Exception:
            pass

    allowed = len(reasons) == 0
    return allowed, requires_confirm, reasons


