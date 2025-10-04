from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml
from apscheduler.schedulers.background import BackgroundScheduler

from src.app.orchestration.router import ToolRouter, ToolRequest
from src.app.adapters.finam_client import FinamAPIClient
from src.app.telegram.registry import list_chats
from src.app.telegram.bot import TelegramBot
from src.app.portfolio.aggregate import get_portfolio_snapshot
from src.app.alerts.state import AlertStateStore


@dataclass
class AlertEvent:
    kind: str
    payload: Dict[str, Any]


class Sink:
    name: str = "sink"

    def send(self, event: AlertEvent) -> None:  # pragma: no cover
        raise NotImplementedError


class StreamlitSink(Sink):
    def __init__(self) -> None:
        pass  # UI will pull events from a shared buffer if needed
    name = "ui"

    def send(self, event: AlertEvent) -> None:
        # Placeholder – integrate with UI session/state as needed
        pass


class TelegramSink(Sink):
    def __init__(self, bot_token: str) -> None:
        self.bot = TelegramBot(bot_token)
        self.name = "telegram"

    def send(self, event: AlertEvent) -> None:
        text = f"[{event.kind}] {event.payload.get('message', '')}"
        for chat_id in list_chats():
            try:
                self.bot.send_message(chat_id, text)
            except Exception:
                continue


class AlertsEngine:
    def __init__(self, router: ToolRouter, sinks: List[Sink]) -> None:
        self.router = router
        self.sinks = sinks
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self.state = AlertStateStore()

    def load_config(self, path: str) -> Dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def start(self, config: Dict[str, Any]) -> None:
        for job in config.get("jobs", []):
            cron = job.get("cron", "*/1 * * * *")
            rule = job.get("rule", {})
            self.scheduler.add_job(self._run_rule, "cron", **self._parse_cron(cron), args=[rule])
        self.scheduler.start()

    def stop(self) -> None:
        self.scheduler.shutdown(wait=False)

    def _parse_cron(self, expr: str) -> Dict[str, Any]:
        # very simple: m h dom mon dow
        parts = expr.split()
        fields = ["minute", "hour", "day", "month", "day_of_week"]
        return {fields[i]: parts[i] for i in range(min(len(parts), 5))}

    def _emit(self, kind: str, payload: Dict[str, Any], channels: Optional[List[str]] = None) -> None:
        event = AlertEvent(kind=kind, payload=payload)
        target = set(channels or [])
        for s in self.sinks:
            if target and s.name not in target:
                continue
            try:
                s.send(event)
            except Exception:
                continue

    def _should_suppress(self, key: str, suppression_minutes: int, cooldown_minutes: int) -> bool:
        from datetime import datetime, timezone, timedelta

        st = self.state.get(key)
        if not st.last_sent_at:
            return False
        try:
            last = datetime.strptime(st.last_sent_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            return False
        now = datetime.now(timezone.utc)
        if suppression_minutes and now - last < timedelta(minutes=suppression_minutes):
            return True
        if cooldown_minutes and now - last < timedelta(minutes=cooldown_minutes):
            return True
        return False

    def _run_rule(self, rule: Dict[str, Any]) -> None:
        kind = rule.get("kind")
        if kind == "price_move":
            symbols = rule.get("symbols") or [rule.get("symbol")]
            threshold = float(rule.get("pct", 1.0))
            channels = rule.get("channels")
            deeplink_tpl = rule.get("deeplink")
            from datetime import datetime, timezone

            for symbol in filter(None, symbols):
                self.router.execute(ToolRequest(method="GET", path=f"/v1/instruments/{symbol}/quotes/latest"))
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                ui_base = os.getenv("UI_BASE_URL", "http://localhost:8501")
                link = f"{ui_base}?symbol={symbol}"
                if deeplink_tpl:
                    link = deeplink_tpl.replace("{UI_BASE_URL}", ui_base).replace("{symbol}", str(symbol))
                self._emit(
                    "price_move",
                    {"symbol": symbol, "time": now, "threshold_pct": threshold, "message": f"{symbol}: price move check ≥{threshold}%. {link}"},
                    channels=channels,
                )
        elif kind == "volume_spike":
            symbols = rule.get("symbols") or [rule.get("symbol")]
            channels = rule.get("channels")
            deeplink_tpl = rule.get("deeplink")
            from datetime import datetime, timezone

            for symbol in filter(None, symbols):
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                ui_base = os.getenv("UI_BASE_URL", "http://localhost:8501")
                link = f"{ui_base}?symbol={symbol}"
                if deeplink_tpl:
                    link = deeplink_tpl.replace("{UI_BASE_URL}", ui_base).replace("{symbol}", str(symbol))
                self._emit("volume_spike", {"symbol": symbol, "time": now, "message": f"{symbol}: volume spike check. {link}"}, channels=channels)
        elif kind == "transactions":
            account_id = rule["account_id"]
            self.router.execute(ToolRequest(method="GET", path=f"/v1/accounts/{account_id}/transactions"))
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._emit("transactions", {"account_id": account_id, "time": now, "message": "Transactions check"}, channels=rule.get("channels"))
        elif kind == "risk":
            account_id = rule["account_id"]
            self.router.execute(ToolRequest(method="GET", path=f"/v1/accounts/{account_id}"))
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._emit("risk", {"account_id": account_id, "time": now, "message": "Risk metrics check"}, channels=rule.get("channels"))
        elif kind == "portfolio_drawdown":
            account_id = rule["account_id"]
            threshold = float(rule.get("threshold_pct", 2.0))
            suppression = int(rule.get("suppression_minutes", 0))
            cooldown = int(rule.get("cooldown_minutes", 0))
            state_key = f"dd:{account_id}"
            if self._should_suppress(state_key, suppression, cooldown):
                return
            snap = get_portfolio_snapshot(self.router, account_id)  # type: ignore[arg-type]
            # Simplified: use current equity vs last stored equity (could persist); here just emit info
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            ui_base = os.getenv("UI_BASE_URL", "http://localhost:8501")
            deeplink_tpl = rule.get("deeplink", "{UI_BASE_URL}")
            deeplink = deeplink_tpl.replace("{UI_BASE_URL}", ui_base).replace("{account_id}", str(account_id))
            self._emit(
                "portfolio_drawdown",
                {
                    "account_id": account_id,
                    "time": now,
                    "message": f"Equity check for DD ≥{threshold}% {deeplink}",
                    "equity": snap.equity,
                },
                channels=rule.get("channels"),
            )
            # Update state
            from datetime import datetime as _dt, timezone as _tz

            self.state.set(state_key, last_value=float(snap.equity or 0.0), last_sent_at=_dt.now(_tz.utc))
        elif kind == "margin_usage":
            account_id = rule["account_id"]
            threshold = float(rule.get("threshold_pct", 50.0))
            suppression = int(rule.get("suppression_minutes", 0))
            cooldown = int(rule.get("cooldown_minutes", 0))
            state_key = f"mu:{account_id}"
            if self._should_suppress(state_key, suppression, cooldown):
                return
            # Placeholder: fetch account and try read margin usage if present
            acct = self.router.execute(ToolRequest(method="GET", path=f"/v1/accounts/{account_id}"))
            usage = acct.get("margin_usage_pct") if isinstance(acct, dict) else None
            ui_base = os.getenv("UI_BASE_URL", "http://localhost:8501")
            deeplink_tpl = rule.get("deeplink", "{UI_BASE_URL}")
            deeplink = deeplink_tpl.replace("{UI_BASE_URL}", ui_base).replace("{account_id}", str(account_id))
            self._emit("margin_usage", {"account_id": account_id, "message": f"Margin usage check ≥{threshold}% {deeplink}", "value": usage}, channels=rule.get("channels"))
            from datetime import datetime as _dt, timezone as _tz

            self.state.set(state_key, last_value=float(usage or 0.0), last_sent_at=_dt.now(_tz.utc))


def build_default_engine(backend: str = "http") -> AlertsEngine:
    client = FinamAPIClient()
    router = ToolRouter(client, backend=backend)
    sinks: List[Sink] = []
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if bot_token:
        sinks.append(TelegramSink(bot_token))
    sinks.append(StreamlitSink())
    return AlertsEngine(router, sinks)


