from __future__ import annotations

import json
import os
import time
from collections import deque
from dataclasses import asdict, dataclass
from typing import Any, Deque, List, Optional


@dataclass
class AuditRecord:
    ts: float
    kind: str
    api_method: Optional[str]
    api_path: Optional[str]
    decision: Optional[str]
    reasons: List[str]
    context: dict


class AuditLogger:
    def __init__(self, maxlen: int = 200) -> None:
        self._buf: Deque[AuditRecord] = deque(maxlen=maxlen)
        self._file_path: Optional[str] = os.getenv("APP_AUDIT_LOG_PATH")

    def log(self, record: AuditRecord) -> None:
        self._buf.append(record)
        if self._file_path:
            try:
                with open(self._file_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
            except Exception:
                pass

    def log_safety(self, api_method: Optional[str], api_path: Optional[str], decision: str, reasons: List[str], context: dict) -> None:
        rec = AuditRecord(ts=time.time(), kind="safety", api_method=api_method, api_path=api_path, decision=decision, reasons=reasons, context=context)
        self.log(rec)

    def recent(self, n: int = 50) -> List[dict]:
        return [asdict(r) for r in list(self._buf)[-n:]]


_LOGGER: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _LOGGER
    if _LOGGER is None:
        _LOGGER = AuditLogger()
    return _LOGGER


