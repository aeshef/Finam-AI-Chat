from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.app.orchestration.router import ToolRouter, ToolRequest
from src.app.core.normalize import infer_market_symbol


@dataclass
class Position:
    symbol: str
    quantity: float
    last_price: float
    market_value: float
    sector: str
    country: str


@dataclass
class PortfolioSnapshot:
    account_id: str
    positions: List[Position]
    cash: Dict[str, float]
    equity: float


def _safe_get(d: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _extract_positions(account_resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Try common keys and a few nested shapes
    for key in ("positions", "Positions", "data", "holdings", "portfolio", "securities", "instruments"):
        val = account_resp.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            for kk in ("items", "data", "positions"):
                vv = val.get(kk)
                if isinstance(vv, list):
                    return vv
    # Look into first list-like value
    for v in account_resp.values():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            return v
    return []


def _extract_cash(account_resp: Dict[str, Any]) -> Dict[str, float]:
    # Expect balances by currency if present
    balances = account_resp.get("balances") or account_resp.get("cash") or {}
    if isinstance(balances, dict):
        out: Dict[str, float] = {}
        for k, v in balances.items():
            try:
                if isinstance(v, dict):
                    val = v.get("amount") or v.get("value") or next((float(x) for x in v.values() if isinstance(x, (int, float, str))), 0.0)
                    out[k] = float(val)
                elif isinstance(v, (int, float, str)):
                    out[k] = float(v)
            except Exception:
                continue
        return out
    if isinstance(balances, list):
        # common shapes:
        # 1) [{"currency":"RUB","amount":123.45}, ...]
        # 2) [{"currency_code":"RUB", "units":"4598", "nanos":310000000}, ...] (Finam)
        out: Dict[str, float] = {}
        for item in balances:
            if not isinstance(item, dict):
                continue
            cur = item.get("currency") or item.get("currency_code") or item.get("code") or "UNK"
            try:
                if "units" in item or "nanos" in item:
                    units = float(item.get("units", 0) or 0)
                    nanos = float(item.get("nanos", 0) or 0)
                    amt = units + nanos / 1_000_000_000.0
                else:
                    raw_val = item.get("amount") or item.get("value")
                    if raw_val is None:
                        # fallback: first numeric-ish value
                        raw_val = next((x for x in item.values() if isinstance(x, (int, float, str))), 0.0)
                    amt = float(raw_val)
                out[str(cur)] = float(amt)
            except Exception:
                continue
        return out
    return {}


def _get_symbol(pos: Dict[str, Any]) -> Optional[str]:
    sym = pos.get("symbol") or pos.get("ticker") or pos.get("instrument")
    if isinstance(sym, dict):
        for k in ("symbol", "ticker", "code"):
            if sym.get(k):
                sym = sym.get(k)
                break
    if isinstance(sym, str) and sym:
        # Auto-append MIC if missing
        if "@" not in sym and sym.isupper():
            try:
                sym = infer_market_symbol(sym)
            except Exception:
                pass
        return sym
    return None


def _get_quantity(pos: Dict[str, Any]) -> float:
    for k in ("quantity", "qty", "position", "amount", "balance", "balanceQty", "lots", "lots_count", "quantityLots"):
        v = pos.get(k)
        if v is not None:
            try:
                if isinstance(v, dict):
                    for kk in ("value", "units", "amount"):
                        if v.get(kk) is not None:
                            return float(v.get(kk))
                    # fallback: first numeric
                    for vv in v.values():
                        try:
                            return float(vv)
                        except Exception:
                            continue
                    return 0.0
                return float(v)
            except Exception:
                return 0.0
    return 0.0


def _fetch_last_price(router: ToolRouter, symbol: str) -> float:
    try:
        q = router.execute(ToolRequest(method="GET", path=f"/v1/instruments/{symbol}/quotes/latest"))
        if isinstance(q, dict):
            # direct fields
            for key in ("last", "price", "close", "value"):
                v = q.get(key)
                if isinstance(v, (int, float, str)):
                    return float(v)
                if isinstance(v, dict) and v.get("value") is not None:
                    try:
                        return float(v.get("value"))
                    except Exception:
                        pass
    except Exception:
        pass
    return 0.0


def _fetch_sector(router: ToolRouter, symbol: str) -> str:
    try:
        a = router.execute(ToolRequest(method="GET", path=f"/v1/assets/{symbol}"))
        for key in ("sector", "industry", "board", "class"):
            v = a.get(key) if isinstance(a, dict) else None
            if isinstance(v, str) and v:
                return v
    except Exception:
        pass
    return "UNKNOWN"


def _fetch_country(router: ToolRouter, symbol: str) -> str:
    try:
        a = router.execute(ToolRequest(method="GET", path=f"/v1/assets/{symbol}"))
        for key in ("country", "Country", "region"):
            v = a.get(key) if isinstance(a, dict) else None
            if isinstance(v, str) and v:
                return v
    except Exception:
        pass
    return "UNKNOWN"


def get_portfolio_snapshot(router: ToolRouter, account_id: string) -> PortfolioSnapshot:  # type: ignore[name-defined]
    # Fetch account
    acct = router.execute(ToolRequest(method="GET", path=f"/v1/accounts/{account_id}"))
    raw_positions = _extract_positions(acct)
    # If not found in account payload, probe common endpoints
    if not raw_positions:
        for ep in (f"/v1/accounts/{account_id}/positions", f"/v1/accounts/{account_id}/portfolio", f"/v1/accounts/{account_id}/holdings"):
            try:
                resp = router.execute(ToolRequest(method="GET", path=ep))
                if isinstance(resp, list) and resp:
                    raw_positions = resp
                    break
                if isinstance(resp, dict):
                    for key in ("positions", "items", "data", "holdings", "securities"):
                        v = resp.get(key)
                        if isinstance(v, list) and v:
                            raw_positions = v
                            break
                if raw_positions:
                    break
            except Exception:
                continue
    cash = _extract_cash(acct)

    positions: List[Position] = []
    equity = 0.0
    for rp in raw_positions:
        symbol = _get_symbol(rp)
        if not symbol:
            continue
        qty = _get_quantity(rp)
        if qty == 0:
            continue
        last = _fetch_last_price(router, symbol)
        # Fallback to current/average price from account payload if quote missing
        if last <= 0:
            try:
                cp = rp.get("current_price") or rp.get("currentPrice") or rp.get("price")
                if isinstance(cp, dict) and cp.get("value") is not None:
                    last = float(cp.get("value"))
                elif isinstance(cp, (int, float, str)):
                    last = float(cp)
            except Exception:
                pass
        if last <= 0:
            try:
                ap = rp.get("average_price") or rp.get("avgPrice")
                if isinstance(ap, dict) and ap.get("value") is not None:
                    last = float(ap.get("value"))
                elif isinstance(ap, (int, float, str)):
                    last = float(ap)
            except Exception:
                pass
        sector = _fetch_sector(router, symbol)
        country = _fetch_country(router, symbol)
        mv = qty * last
        equity += mv
        positions.append(Position(symbol=symbol, quantity=qty, last_price=last, market_value=mv, sector=sector, country=country))

    # Add cash to equity as sum of all currencies (rough; for detailed FX convert)
    equity += sum(cash.values()) if cash else 0.0

    return PortfolioSnapshot(account_id=account_id, positions=positions, cash=cash, equity=equity)


def build_sunburst_data(snapshot: PortfolioSnapshot) -> Dict[str, Any]:
    # Build hierarchical data sector -> symbol -> value
    labels: List[str] = []
    parents: List[str] = []
    values: List[float] = []

    root = "Portfolio"
    labels.append(root)
    parents.append("")
    values.append(snapshot.equity)

    # Aggregate by sector
    sector_values: Dict[str, float] = {}
    for p in snapshot.positions:
        sector_values[p.sector] = sector_values.get(p.sector, 0.0) + p.market_value

    for sector, val in sector_values.items():
        labels.append(sector)
        parents.append(root)
        values.append(val)

    for p in snapshot.positions:
        labels.append(p.symbol)
        parents.append(p.sector)
        values.append(p.market_value)

    return {"labels": labels, "parents": parents, "values": values}


def compute_target_weights_equal(snapshot: PortfolioSnapshot) -> Dict[str, float]:
    symbols = [p.symbol for p in snapshot.positions]
    n = len(symbols)
    if n == 0:
        return {}
    w = 1.0 / n
    return {s: w for s in symbols}


def plan_rebalance(
    snapshot: PortfolioSnapshot,
    targets: Dict[str, float],
    min_trade_value: float = 0.0,
    lot_sizes: Optional[Dict[str, int]] = None,
    commission_fixed: float = 0.0,
    commission_pct: float = 0.0,
) -> List[Dict[str, Any]]:
    # Compute desired MV per symbol; assume equity known
    desired_mv = {sym: targets.get(sym, 0.0) * snapshot.equity for sym in targets.keys()}
    cur_mv = {p.symbol: p.market_value for p in snapshot.positions}
    prices = {p.symbol: p.last_price for p in snapshot.positions}
    suggestions: List[Dict[str, Any]] = []
    for sym, d_mv in desired_mv.items():
        delta = d_mv - cur_mv.get(sym, 0.0)
        if abs(delta) < min_trade_value:
            continue
        price = prices.get(sym) or 0.0
        if price <= 0:
            continue
        qty = int(delta / price)
        # apply lot size rounding
        lot = 1
        if lot_sizes and sym in lot_sizes:
            try:
                lot = max(1, int(lot_sizes[sym]))
            except Exception:
                lot = 1
        if qty > 0:
            qty = (qty // lot) * lot
        else:
            qty = -(((-qty) // lot) * lot)
        if qty == 0:
            continue
        # estimate commissions and skip tiny trades where commission dominates
        notional = abs(qty) * price
        est_fee = commission_fixed + commission_pct * notional
        if notional <= est_fee * 2:  # skip if fee too large relative to trade
            continue
        action = "buy" if qty > 0 else "sell"
        suggestions.append({
            "symbol": sym,
            "action": action,
            "quantity": abs(qty),
            "price_ref": price,
            "est_notional": notional,
            "est_fee": est_fee,
        })
    return suggestions




