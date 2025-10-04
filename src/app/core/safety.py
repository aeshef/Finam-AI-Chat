from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class OrderSafetySummary:
    symbol: str
    side: str
    order_type: str
    quantity: int
    price: Optional[float]
    stop_price: Optional[float]
    time_in_force: Optional[str]
    warnings: list[str]


def build_order_summary(order: Dict[str, Any]) -> OrderSafetySummary:
    return OrderSafetySummary(
        symbol=str(order.get("instrument", "")),
        side=str(order.get("side", "")),
        order_type=str(order.get("type", "")),
        quantity=int(order.get("quantity", 0) or 0),
        price=(float(order["price"]) if "price" in order and order["price"] is not None else None),
        stop_price=(
            float(order["stop_price"]) if "stop_price" in order and order["stop_price"] is not None else None
        ),
        time_in_force=str(order.get("time_in_force", "")) or None,
        warnings=[],
    )


def sanity_checks(summary: OrderSafetySummary, last_price: Optional[float] = None) -> OrderSafetySummary:
    warnings: list[str] = []
    if summary.quantity <= 0:
        warnings.append("Quantity is not positive")
    if summary.order_type in {"limit", "stop_limit", "take_profit_limit"} and summary.price is None:
        warnings.append("Limit-like order without price")
    if summary.order_type in {"stop_market", "stop_limit"} and summary.stop_price is None:
        warnings.append("Stop order without stop_price")
    if last_price is not None and summary.price is not None:
        # Simple anti-high heuristic: avoid limit buy far above last price
        if summary.side == "buy" and summary.price > last_price * 1.02:
            warnings.append("Limit buy price > 2% above last trade")
        if summary.side == "sell" and summary.price < last_price * 0.98:
            warnings.append("Limit sell price < 2% below last trade")
    summary.warnings = warnings
    return summary



