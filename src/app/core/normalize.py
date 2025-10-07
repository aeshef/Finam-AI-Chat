from __future__ import annotations

from typing import Literal, Any, Dict, Tuple, Optional
from datetime import datetime, date, timezone, timedelta


Timeframe = Literal[
    "TIME_FRAME_M1",
    "TIME_FRAME_M5",
    "TIME_FRAME_M15",
    "TIME_FRAME_M30",
    "TIME_FRAME_H1",
    "TIME_FRAME_H4",
    "TIME_FRAME_D",
    "TIME_FRAME_W",
    "TIME_FRAME_MN",
]


def normalize_timeframe(natural: str) -> Timeframe:
    s = natural.strip().lower()
    if any(k in s for k in ["1m", "m1", "минутная", "минутные", "1 мин", "1‑мин"]):
        return "TIME_FRAME_M1"
    if any(k in s for k in ["5m", "m5", "5 мин", "5‑мин"]):
        return "TIME_FRAME_M5"
    if any(k in s for k in ["15m", "m15", "15 мин"]):
        return "TIME_FRAME_M15"
    if any(k in s for k in ["30m", "m30", "30 мин"]):
        return "TIME_FRAME_M30"
    if any(k in s for k in ["1h", "h1", "час", "часовой"]):
        return "TIME_FRAME_H1"
    if any(k in s for k in ["4h", "h4", "4 часа", "4‑час"]):
        return "TIME_FRAME_H4"
    if any(k in s for k in ["d", "1d", "day", "днев", "дни"]):
        return "TIME_FRAME_D"
    if any(k in s for k in ["w", "1w", "нед", "недел"]):
        return "TIME_FRAME_W"
    if any(k in s for k in ["mn", "mon", "месяц", "месячн"]):
        return "TIME_FRAME_MN"
    # fallback
    return "TIME_FRAME_D"


def normalize_iso8601(natural: Any) -> str:
    """Normalize common date inputs to ISO8601 Z.

    Accepts YYYY-MM-DD, YYYY/MM/DD, 'YYYY-MM-DD HH:MM', and returns 'YYYY-MM-DDTHH:MM:SSZ'.
    Fallback: current day start UTC.
    """
    # Handle datetime/date objects directly
    now = datetime.now(timezone.utc)
    if isinstance(natural, datetime):
        dt = natural.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(natural, date):
        dt = datetime(year=natural.year, month=natural.month, day=natural.day, tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    s = str(natural).strip()
    nl = s.lower()
    # NL shortcuts
    if nl in {"сегодня", "today"}:
        start = datetime(year=now.year, month=now.month, day=now.day, tzinfo=timezone.utc)
        return start.strftime("%Y-%m-%dT%H:%M:%SZ")
    if nl in {"вчера", "yesterday"}:
        y = now - timedelta(days=1)
        start = datetime(year=y.year, month=y.month, day=y.day, tzinfo=timezone.utc)
        return start.strftime("%Y-%m-%dT%H:%M:%SZ")
    if nl in {"неделя", "за неделю", "last week"}:
        return (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if nl.startswith("последние ") and " дней" in nl:
        try:
            num = int(nl.split("последние ")[1].split(" дней")[0].strip())
            return (now - timedelta(days=num)).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            pass
    fmts = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ]
    for f in fmts:
        try:
            dt = datetime.strptime(s, f).replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            continue
    # fallback to start of current day UTC
    start = datetime(year=now.year, month=now.month, day=now.day, tzinfo=timezone.utc)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def infer_market_symbol(symbol_like: str) -> str:
    """Attach market if missing (basic heuristic). Example: SBER -> SBER@MISX.

    Responsibility: only format enrichment, no alias resolution (handled by SymbolResolver).
    """
    s = (symbol_like or "").strip()
    if not s:
        return s
    if "@" in s:
        return s
    # Default to Moscow Exchange (can be made configurable or from policy)
    return f"{s}@MISX"


RU_MONTHS = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "мая": 5,
    "май": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}


def _end_of_month(year: int, month: int) -> datetime:
    if month == 12:
        nxt = datetime(year=year + 1, month=1, day=1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year=year, month=month + 1, day=1, tzinfo=timezone.utc)
    return nxt - timedelta(seconds=1)


def _quarter_bounds(year: int, q: int) -> Tuple[datetime, datetime]:
    start_month = 3 * (q - 1) + 1
    start = datetime(year=year, month=start_month, day=1, tzinfo=timezone.utc)
    end_month = start_month + 2
    end = _end_of_month(year, end_month)
    return start, end


def parse_date_range(natural_text: str) -> Optional[Tuple[str, str]]:
    """Parse Russian natural phrases into ISO8601 start/end.

    Handles: 'август 2025', 'за последний квартал', 'последнюю неделю', 'вчера', 'сегодня'.
    """
    if not natural_text:
        return None
    text = natural_text.lower()
    now = datetime.now(timezone.utc)

    # direct shortcuts already handled by normalize_iso8601, but include here for pairs
    if "последн" in text and "недел" in text:
        start = now - timedelta(days=7)
        s = datetime(year=start.year, month=start.month, day=start.day, tzinfo=timezone.utc)
        e = now
        return s.strftime("%Y-%m-%dT%H:%M:%SZ"), e.strftime("%Y-%m-%dT%H:%M:%SZ")

    if "последн" in text and "квартал" in text:
        # last quarter bounds
        q = ((now.month - 1) // 3)  # 0..3, previous quarter index
        if q == 0:
            year = now.year - 1
            q = 4
        else:
            year = now.year
        start, end = _quarter_bounds(year, q)
        return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")

    # half-year phrases
    if "полгод" in text or "пол-года" in text or "за полгода" in text:
        start_dt = now - timedelta(days=182)
        s = datetime(year=start_dt.year, month=start_dt.month, day=start_dt.day, tzinfo=timezone.utc)
        e = now
        return s.strftime("%Y-%m-%dT%H:%M:%SZ"), e.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 'август 2025' like
    import re as _re

    m = _re.search(r"(январ|феврал|март|апрел|мая|май|июн|июл|август|сентябр|октябр|ноябр|декабр)\s+(\d{4})", text)
    if m:
        mon_key = m.group(1)
        year = int(m.group(2))
        month = RU_MONTHS.get(mon_key, None)
        if month:
            start = datetime(year=year, month=month, day=1, tzinfo=timezone.utc)
            end = _end_of_month(year, month)
            return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")

    return None



