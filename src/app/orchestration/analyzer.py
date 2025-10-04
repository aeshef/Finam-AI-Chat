from __future__ import annotations

from typing import Any, Dict


def basic_analyze(response: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal analyzer: passthrough with size guard."""
    # In future: compute summaries/metrics. Keep DRY by centralizing here.
    return response



