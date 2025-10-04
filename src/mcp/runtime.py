from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from urllib.parse import urlparse, parse_qs

from src.mcp.tools import assets as assets_tools
from src.mcp.tools import market_data as md_tools
from src.mcp.tools import accounts as acc_tools
from src.mcp.tools import orders as ord_tools
from src.mcp.tools import sessions as sess_tools
from src.mcp.tools import system as sys_tools


def _parse_path(path: str) -> Tuple[str, list[str], Dict[str, Any]]:
    parsed = urlparse(path)
    segments = [s for s in parsed.path.split("/") if s]
    q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    return parsed.path, segments, q


class MCPRuntime:
    """Lightweight in-process MCP-like router that calls tool functions by METHOD/PATH/params.

    This avoids UI coupling to HTTP and keeps backend selectable.
    """

    def call_raw(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        method = method.upper()
        _, segs, q = _parse_path(path)

        # Assets and Exchanges
        if method == "GET" and segs[:2] == ["v1", "exchanges"]:
            # No dedicated tool for exchanges; re-use assets.list for now if available later
            return {"exchanges": []}
        if method == "GET" and segs[:2] == ["v1", "assets"]:
            if len(segs) == 2:
                return assets_tools.list_assets()
            symbol = segs[2]
            if len(segs) == 3:
                account_id = q.get("account_id")
                return assets_tools.get_instrument(symbol, account_id=account_id)
            if segs[3] == "params":
                return assets_tools.get_params(symbol, account_id=q.get("account_id"))
            if segs[3] == "schedule":
                return assets_tools.get_schedule(symbol)
            if segs[3] == "options":
                return assets_tools.get_options(symbol)

        # Market data
        if method == "GET" and segs[:2] == ["v1", "instruments"]:
            symbol = segs[2]
            leaf = segs[3]
            if leaf == "quotes" and segs[4] == "latest":
                return md_tools.get_quote(symbol)
            if leaf == "orderbook":
                depth = int(q.get("depth", 10))
                return md_tools.get_orderbook(symbol, depth=depth)
            if leaf == "bars":
                timeframe = q.get("timeframe", "D")
                start = q.get("interval.start_time")
                end = q.get("interval.end_time")
                return md_tools.get_bars(symbol, timeframe=timeframe, start=start, end=end)
            if leaf == "trades" and segs[4] == "latest":
                return md_tools.get_trades_latest(symbol)

        # Accounts & Orders
        if segs[:2] == ["v1", "accounts"]:
            account_id = segs[2]
            if method == "GET" and len(segs) == 3:
                return acc_tools.get_account(account_id)
            if len(segs) >= 4 and segs[3] == "orders":
                if method == "GET" and len(segs) == 4:
                    return acc_tools.get_orders(account_id)
                if method == "GET" and len(segs) == 5:
                    return acc_tools.get_order(account_id, segs[4])
                if method == "POST" and len(segs) == 4:
                    order_json = kwargs.get("json", {})
                    return ord_tools.create_order(account_id, order_json)
                if method == "DELETE" and len(segs) == 5:
                    return ord_tools.cancel_order(account_id, segs[4])
            if method == "GET" and segs[3] == "trades":
                return acc_tools.get_trades(account_id, start=q.get("interval.start_time"), end=q.get("interval.end_time"))
            if method == "GET" and segs[3] == "transactions":
                limit = int(q.get("limit")) if q.get("limit") else None
                return acc_tools.get_transactions(account_id, start=q.get("interval.start_time"), end=q.get("interval.end_time"), limit=limit)

        # Sessions
        if method == "POST" and segs[:3] == ["v1", "sessions", "details"]:
            return sess_tools.details()
        if method == "POST" and segs[:2] == ["v1", "sessions"] and len(segs) == 2:
            return sess_tools.create()

        # System time (virtual endpoint)
        if method == "GET" and segs[:3] == ["v1", "system", "time"]:
            return sys_tools.server_time()

        return {"error": "Not implemented in MCP runtime", "path": path, "method": method}


