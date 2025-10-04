from __future__ import annotations

from typing import Any, Dict, Optional

from src.app.adapters.finam_client import FinamAPIClient


def get_account(account_id: str, client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("GET", f"/v1/accounts/{account_id}")


def get_orders(account_id: str, client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("GET", f"/v1/accounts/{account_id}/orders")


def get_order(account_id: str, order_id: str, client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("GET", f"/v1/accounts/{account_id}/orders/{order_id}")


def get_trades(
    account_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    client: Optional[FinamAPIClient] = None,
) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    params: Dict[str, Any] = {}
    if start:
        params["interval.start_time"] = start
    if end:
        params["interval.end_time"] = end
    return client.execute_request("GET", f"/v1/accounts/{account_id}/trades", params=params)


def get_transactions(
    account_id: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: Optional[int] = None,
    client: Optional[FinamAPIClient] = None,
) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    params: Dict[str, Any] = {}
    if start:
        params["interval.start_time"] = start
    if end:
        params["interval.end_time"] = end
    if limit is not None:
        params["limit"] = limit
    return client.execute_request("GET", f"/v1/accounts/{account_id}/transactions", params=params)



