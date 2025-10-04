from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class AlertStateEntry:
    last_value: Optional[float] = None
    last_sent_at: Optional[str] = None  # ISO8601 UTC


class AlertStateStore:
    def __init__(self, path: str = "data/alerts_state.json") -> None:
        self.path = path
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if os.path.exists(self.path):
                with open(self.path, encoding="utf-8") as f:
                    self._cache = json.load(f)
        except Exception:
            self._cache = {}

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get(self, key: str) -> AlertStateEntry:
        obj = self._cache.get(key) or {}
        return AlertStateEntry(last_value=obj.get("last_value"), last_sent_at=obj.get("last_sent_at"))

    def set(self, key: str, last_value: Optional[float], last_sent_at: Optional[datetime]) -> None:
        self._cache[key] = {
            "last_value": last_value,
            "last_sent_at": _utc_iso(last_sent_at) if isinstance(last_sent_at, datetime) else last_sent_at,
        }
        self._save()


