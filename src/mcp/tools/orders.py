from __future__ import annotations

from typing import Any, Dict, Optional

from src.app.adapters.finam_client import FinamAPIClient


def create_order(account_id: str, order_data: Dict[str, Any], client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("POST", f"/v1/accounts/{account_id}/orders", json=order_data)


def cancel_order(account_id: str, order_id: str, client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("DELETE", f"/v1/accounts/{account_id}/orders/{order_id}")



