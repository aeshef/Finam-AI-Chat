from __future__ import annotations

import re
from typing import Dict, List, Tuple


PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")


def find_placeholders(path: str) -> List[str]:
    return PLACEHOLDER_RE.findall(path)


def substitute_placeholders(path: str, params: Dict[str, str]) -> Tuple[str, List[str]]:
    missing: List[str] = []
    def _repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in params and params[key]:
            return str(params[key])
        missing.append(key)
        return match.group(0)

    new_path = PLACEHOLDER_RE.sub(_repl, path)
    return new_path, missing



