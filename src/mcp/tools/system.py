from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def server_time() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {"server_time": now.strftime("%Y-%m-%dT%H:%M:%SZ")}


