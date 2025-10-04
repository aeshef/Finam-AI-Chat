from __future__ import annotations

import os
from typing import Any

import requests

from src.app.telegram.registry import add_chat
from src.app.orchestration.router import ToolRouter, ToolRequest
from src.app.adapters.finam_client import FinamAPIClient


class TelegramBot:
    def __init__(self, token: str) -> None:
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"

    def send_message(self, chat_id: int, text: str) -> None:
        requests.post(f"{self.base}/sendMessage", json={"chat_id": chat_id, "text": text}, timeout=10)

    def set_webhook(self, url: str) -> Any:
        return requests.post(f"{self.base}/setWebhook", json={"url": url}, timeout=10).json()

    def get_updates(self, offset: int | None = None) -> Any:
        params = {"timeout": 60}
        if offset is not None:
            params["offset"] = offset
        return requests.get(f"{self.base}/getUpdates", params=params, timeout=70).json()


def run_polling() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("TELEGRAM_BOT_TOKEN is empty")
        return
    bot = TelegramBot(token)
    last_update_id: int | None = None
    print("Telegram bot polling started")
    router = ToolRouter(FinamAPIClient())
    while True:
        try:
            data = bot.get_updates(offset=(last_update_id + 1) if last_update_id else None)
            if not data.get("ok"):
                continue
            for update in data.get("result", []):
                last_update_id = update["update_id"]
                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue
                chat_id = msg["chat"]["id"]
                text = (msg.get("text") or "").strip()
                if text.startswith("/start"):
                    add_chat(int(chat_id))
                    bot.send_message(chat_id, "Бот подключен к алертам. Вы будете получать уведомления.")
                elif text.startswith("/quote "):
                    # /quote SBER@MISX
                    symbol = text.split(maxsplit=1)[1].strip()
                    resp = router.execute(ToolRequest(method="GET", path=f"/v1/instruments/{symbol}/quotes/latest"))
                    bot.send_message(chat_id, f"{symbol}: запрос котировки отправлен")
                elif text.startswith("/confirm "):
                    # /confirm METHOD PATH
                    try:
                        parts = text.split(maxsplit=2)
                        method = parts[1].upper()
                        path = parts[2]
                        resp = router.execute(ToolRequest(method=method, path=path))
                        bot.send_message(chat_id, f"Подтверждено: {method} {path}")
                    except Exception:
                        bot.send_message(chat_id, "Неверный формат. Используйте: /confirm METHOD /path")
        except Exception:
            continue


if __name__ == "__main__":
    run_polling()


