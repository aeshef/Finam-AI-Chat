from __future__ import annotations

import re
from typing import Any, Dict, Optional, List

from src.app.orchestration.router import ToolRouter, ToolRequest


def extract_symbol_from_text(text: str) -> Optional[str]:
    m = re.search(r"([A-Z0-9_.-]+@[A-Z]+)", text)
    return m.group(1) if m else None


def compute_market_insights(router: ToolRouter, symbol: str) -> Dict[str, Any]:
    insights: Dict[str, Any] = {"symbol": symbol}
    try:
        quote = router.execute(ToolRequest(method="GET", path=f"/v1/instruments/{symbol}/quotes/latest"))
        orderbook = router.execute(ToolRequest(method="GET", path=f"/v1/instruments/{symbol}/orderbook"))
        # Heuristic metrics (keep generic)
        best_bid = None
        best_ask = None
        bid_sz: float = 0.0
        ask_sz: float = 0.0
        impact_px: Optional[float] = None
        try:
            bids: List[Dict[str, Any]] = orderbook.get("bids") or orderbook.get("rows") or []
            asks: List[Dict[str, Any]] = orderbook.get("asks") or orderbook.get("rows") or []
            if bids:
                best_bid = bids[0].get("price") or bids[0].get("bid") or bids[0].get("p")
                bid_sz = float(bids[0].get("size") or bids[0].get("buy_size") or 0.0)
            if asks:
                best_ask = asks[0].get("price") or asks[0].get("ask") or asks[0].get("p")
                ask_sz = float(asks[0].get("size") or asks[0].get("sell_size") or 0.0)
        except Exception:
            pass
        if best_bid is not None and best_ask is not None:
            spread = float(best_ask) - float(best_bid)
            mid = (float(best_ask) + float(best_bid)) / 2.0
            insights["spread"] = spread
            insights["spread_bps"] = (spread / mid * 10000.0) if mid else None
            insights["best_bid_size"] = bid_sz
            insights["best_ask_size"] = ask_sz
        # Placeholder for day range if available in quote
        last_price = quote.get("last") if isinstance(quote, dict) else None
        insights["last_price"] = last_price

        # Simple impact estimate: move along top 3 levels and compute price to fill notional
        try:
            target_notional = float(quote.get("turnover") or 0.0) * 0.001 if isinstance(quote, dict) else 0.0
            if target_notional > 0 and asks:
                cum = 0.0
                spent = 0.0
                for level in asks[:3]:
                    px = float(level.get("price") or level.get("p") or 0.0)
                    sz = float(level.get("size") or level.get("sell_size") or 0.0)
                    if px <= 0 or sz <= 0:
                        continue
                    vol = min(sz, max(0.0, target_notional - spent) / px)
                    spent += vol * px
                    cum += vol
                    if spent >= target_notional:
                        impact_px = px
                        break
            insights["impact_px"] = impact_px
        except Exception:
            pass
    except Exception:
        pass
    return insights


def suggest_from_insights(insights: Dict[str, Any], side: Optional[str] = None) -> str:
    suggestions: list[str] = []
    spread_bps = insights.get("spread_bps")
    if spread_bps is not None and spread_bps > 20:  # wide spread
        suggestions.append("широкий спрэд → используйте лимит и избегайте рыночных, рассмотрите DAY/GTC")
    if side and insights.get("last_price") is not None:
        lp = float(insights["last_price"])  # noqa: FBT003
        # Generic caution around momentum; keep conservative thresholds
        if side == "buy":
            suggestions.append("для покупки рассмотрите лимит ниже текущей цены или дайте рынку стабилизироваться")
        if side == "sell":
            suggestions.append("для продажи используйте лимит ближе к лучшему бид для снижения импакта")
    # Participation limits
    if insights.get("best_ask_size") and side == "buy":
        suggestions.append("лимит участия ≤ 20% от объёма на лучших ценах")
    if insights.get("best_bid_size") and side == "sell":
        suggestions.append("лимит участия ≤ 20% от объёма на лучших ценах")
    # TIF vs time of day (heuristic placeholder)
    suggestions.append("TIF: в тонкий рынок — DAY/GTC; при высокой ликвидности — IOC/FOK осторожно")
    if suggestions:
        return "; ".join(suggestions)
    return "нет особых ограничений, можно использовать стандартные параметры"


def slicing_profiles(notional: float, duration_min: int = 30, profile: str = "TWAP") -> Dict[str, Any]:
    """Return schedule for slicing notional by profile (TWAP/VWAP/POV, simplified)."""
    profile = (profile or "TWAP").upper()
    steps = max(1, duration_min // 5)
    if profile == "POV":
        # simple: front-load 40%, then 60%
        weights = [0.4] + [0.6 / (steps - 1) for _ in range(steps - 1)]
    else:
        # TWAP/VWAP as equal weights placeholder
        weights = [1.0 / steps for _ in range(steps)]
    schedule = [w * notional for w in weights]
    return {"profile": profile, "steps": steps, "schedule": schedule}


