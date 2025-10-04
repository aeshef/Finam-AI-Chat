from __future__ import annotations

from typing import Any, Dict, Tuple

from src.app.registry.endpoints import EndpointRegistry


def build_from_schema(schema: Any) -> Tuple[str, str, Dict[str, Any]]:
    """Map request schema to (method, path, params) using declarative registry (SSOT)."""
    reg = EndpointRegistry()
    return reg.resolve(schema)



