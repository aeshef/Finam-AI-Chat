from __future__ import annotations

import json
import os
from typing import List


REGISTRY_PATH = os.getenv("TELEGRAM_CHAT_REGISTRY", "configs/telegram_chats.json")


def _load() -> List[int]:
    if not os.path.exists(REGISTRY_PATH):
        return []
    try:
        data = json.loads(open(REGISTRY_PATH, encoding="utf-8").read())
        return [int(x) for x in data.get("chats", [])]
    except Exception:
        return []


def _save(chats: List[int]) -> None:
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump({"chats": list(sorted(set(chats)))}, f, ensure_ascii=False, indent=2)


def add_chat(chat_id: int) -> None:
    chats = _load()
    if chat_id not in chats:
        chats.append(chat_id)
        _save(chats)


def list_chats() -> List[int]:
    return _load()


