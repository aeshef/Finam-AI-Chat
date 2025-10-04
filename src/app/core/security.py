from __future__ import annotations

import hashlib
import os
import time
from typing import Optional


_idempotency_store: dict[str, float] = {}


def generate_intent_hash(method: str, path: str, body: str | None = None) -> str:
    raw = f"{method}|{path}|{body or ''}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def check_and_remember_idempotency(key: str, ttl_seconds: Optional[int] = None) -> bool:
    ttl = ttl_seconds or int(os.getenv("IDEMPOTENCY_TTL_SECONDS", "60"))
    now = time.time()
    # purge old
    for k, t in list(_idempotency_store.items()):
        if now - t > ttl:
            _idempotency_store.pop(k, None)
    if key in _idempotency_store:
        return False
    _idempotency_store[key] = now
    return True
