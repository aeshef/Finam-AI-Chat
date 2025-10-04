from __future__ import annotations

from typing import Any, Dict, Optional

from src.app.adapters.finam_client import FinamAPIClient


def details(client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("POST", "/v1/sessions/details")


def create(client: Optional[FinamAPIClient] = None) -> Dict[str, Any]:
    client = client or FinamAPIClient()
    return client.execute_request("POST", "/v1/sessions")



