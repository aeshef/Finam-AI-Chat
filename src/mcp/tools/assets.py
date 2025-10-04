from __future__ import annotations

from typing import Any, Dict, Optional

from src.app.adapters.finam_client import FinamAPIClient


def list_assets(client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("GET", "/v1/assets")


def get_instrument(symbol: str, account_id: Optional[str] = None, client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    path = f"/v1/assets/{symbol}"
    if account_id:
        path = f"{path}?account_id={account_id}"
    return client.execute_request("GET", path)


def get_params(symbol: str, account_id: Optional[str] = None, client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    path = f"/v1/assets/{symbol}/params"
    if account_id:
        path = f"{path}?account_id={account_id}"
    return client.execute_request("GET", path)


def get_schedule(symbol: str, client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("GET", f"/v1/assets/{symbol}/schedule")


def get_options(symbol: str, client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("GET", f"/v1/assets/{symbol}/options")



