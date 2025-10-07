from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.app.core.normalize import normalize_timeframe, normalize_iso8601
from src.app.orchestration.router import ToolRouter, ToolRequest


@dataclass
class ScanCriteria:
    symbols: List[str]
    timeframe: str  # TIME_FRAME_*
    start: str
    end: str
    min_growth_pct: Optional[float] = None
    min_volume: Optional[float] = None
    require_short: bool = False
    account_id: Optional[str] = None


@dataclass
class ScanResult:
    symbol: str
    growth_pct: Optional[float]
    total_volume: Optional[float]
    short_available: Optional[bool]
    sparkline: List[float]


def _fetch_bars(router: ToolRouter, symbol: str, timeframe: str, start_iso: str, end_iso: str) -> List[Dict[str, Any]]:
    path = f"/v1/instruments/{symbol}/bars?timeframe={timeframe}&interval.start_time={start_iso}&interval.end_time={end_iso}"
    resp = router.execute(ToolRequest(method="GET", path=path))
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        # Common shapes
        for key in ("bars", "candles", "data", "items", "result"):
            v = resp.get(key)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                for kk in ("items", "data"):
                    vv = v.get(kk)
                    if isinstance(vv, list):
                        return vv
        # Fallback: scan dict values for first list of bar-like dicts
        for v in resp.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and (
                "close" in v[0] or "timestamp" in v[0] or "time" in v[0]
            ):
                return v
        return []
    return []


def _compute_growth_and_volume(bars: List[Dict[str, Any]]) -> tuple[Optional[float], Optional[float], List[float]]:
    closes: List[float] = []
    total_vol = 0.0
    for b in bars:
        try:
            c = b.get("close") or b.get("c") or b.get("price")
            if isinstance(c, dict):
                c = c.get("value")
            if c is not None:
                closes.append(float(c))
            v = b.get("volume") or b.get("v")
            if isinstance(v, dict):
                v = v.get("value")
            if v is not None:
                total_vol += float(v)
        except Exception:
            continue
    growth = None
    if len(closes) >= 2 and closes[0] != 0:
        growth = (closes[-1] / closes[0] - 1.0) * 100.0
    return growth, (total_vol if total_vol > 0 else None), closes


def _check_short_availability(router: ToolRouter, symbol: str, account_id: Optional[str]) -> Optional[bool]:
    try:
        if account_id:
            resp = router.execute(ToolRequest(method="GET", path=f"/v1/assets/{symbol}/params?account_id={account_id}"))
        else:
            resp = router.execute(ToolRequest(method="GET", path=f"/v1/assets/{symbol}/params"))
        # Attempt to read common flags; keep generic and robust
        def _to_bool(x: Any) -> Optional[bool]:
            if isinstance(x, bool):
                return x
            if isinstance(x, str):
                s = x.strip().lower()
                if s in ("true", "yes", "1"): return True
                if s in ("false", "no", "0"): return False
            return None

        def _search_bool(d: Dict[str, Any]) -> Optional[bool]:
            for key in ("short_allowed", "can_short", "shortable", "shortAvailable", "is_shortable"):
                v = d.get(key)
                b = _to_bool(v)
                if b is not None:
                    return b
            # search nested dicts
            for v in d.values():
                if isinstance(v, dict):
                    b = _search_bool(v)
                    if b is not None:
                        return b
            return None

        if isinstance(resp, dict):
            found = _search_bool(resp)
            if found is not None:
                return found
        return None
    except Exception:
        return None


def run_scan(router: ToolRouter, criteria: ScanCriteria) -> List[ScanResult]:
    # Safe defaults
    syms = criteria.symbols or ["SBER@MISX", "GAZP@MISX", "YNDX@MISX"]
    tf = normalize_timeframe(criteria.timeframe or "TIME_FRAME_D")
    start_iso = normalize_iso8601(criteria.start or "последние 30 дней")
    end_iso = normalize_iso8601(criteria.end or "сегодня")

    results: List[ScanResult] = []
    for sym in syms:
        bars = _fetch_bars(router, sym, tf, start_iso, end_iso)
        if not bars:
            continue
        growth, total_volume, closes = _compute_growth_and_volume(bars)
        short_flag = _check_short_availability(router, sym, criteria.account_id) if criteria.require_short else None

        # Filter application
        if criteria.min_growth_pct is not None and (growth is None or growth < criteria.min_growth_pct):
            continue
        if criteria.min_volume is not None and ((total_volume or 0.0) < criteria.min_volume):
            continue
        if criteria.require_short and short_flag is False:
            continue
        results.append(ScanResult(symbol=sym, growth_pct=growth, total_volume=total_volume, short_available=short_flag, sparkline=closes))

    # Sort by growth desc then volume desc
    results.sort(key=lambda r: ((r.growth_pct or 0.0), (r.total_volume or 0.0)), reverse=True)
    return results




