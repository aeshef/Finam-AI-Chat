from __future__ import annotations

from typing import Optional, Tuple


def extract_api_request(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract METHOD and PATH from assistant text with 'API_REQUEST:' pattern.

    Returns (method, path) or (None, None) if not found.
    """
    if "API_REQUEST:" not in text:
        return None, None
    for line in text.splitlines():
        if line.strip().startswith("API_REQUEST:"):
            request = line.replace("API_REQUEST:", "").strip()
            parts = request.split(maxsplit=1)
            if len(parts) == 2:
                return parts[0], parts[1]
    return None, None



