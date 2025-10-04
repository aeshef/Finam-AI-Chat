from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class CacheEntry:
    value: Any
    expires_at: float


class SimpleTTLCache:
    def __init__(self) -> None:
        self._store: Dict[str, CacheEntry] = {}

    def _key(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> str:
        base = f"{method}:{path}"
        if params:
            items = ",".join(f"{k}={v}" for k, v in sorted(params.items()))
            return f"{base}?{items}"
        return base

    def get(self, method: str, path: str, params: Optional[Dict[str, Any]] = None) -> Tuple[bool, Any]:
        k = self._key(method, path, params)
        entry = self._store.get(k)
        now = time.time()
        if entry and entry.expires_at > now:
            return True, entry.value
        if entry:
            self._store.pop(k, None)
        return False, None

    def set(self, method: str, path: str, params: Optional[Dict[str, Any]], value: Any, ttl_seconds: int) -> None:
        k = self._key(method, path, params)
        self._store[k] = CacheEntry(value=value, expires_at=time.time() + ttl_seconds)



