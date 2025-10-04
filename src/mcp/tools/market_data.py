from __future__ import annotations

from typing import Any, Dict, Optional

from src.app.adapters.finam_client import FinamAPIClient


def get_quote(symbol: str, client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("GET", f"/v1/instruments/{symbol}/quotes/latest")


def get_orderbook(symbol: str, depth: int = 10, client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("GET", f"/v1/instruments/{symbol}/orderbook", params={"depth": depth})


def get_bars(
    symbol: str,
    timeframe: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    client: Optional[FinamAPIClient] = None,
) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    params: Dict[str, Any] = {"timeframe": timeframe}
    if start:
        params["interval.start_time"] = start
    if end:
        params["interval.end_time"] = end
    return client.execute_request("GET", f"/v1/instruments/{symbol}/bars", params=params)


def get_trades_latest(symbol: str, client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("GET", f"/v1/instruments/{symbol}/trades/latest")



