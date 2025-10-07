from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.app.orchestration.router import ToolRouter, ToolRequest
from src.app.portfolio.aggregate import PortfolioSnapshot


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_equity_curve(
    router: ToolRouter,
    snapshot: PortfolioSnapshot,
    days: int = 30,
    benchmark_symbol: Optional[str] = None,
) -> Dict[str, List[float]]:
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    dates: List[datetime] = []
    lines: Dict[str, List[float]] = {}

    # Build per-symbol close series
    symbol_to_series: Dict[str, Dict[str, float]] = {}
    for p in snapshot.positions:
        try:
            path = f"/v1/instruments/{p.symbol}/bars?timeframe=TIME_FRAME_D&interval.start_time={_iso(start)}&interval.end_time={_iso(end)}"
            resp = router.execute(ToolRequest(method="GET", path=path))
            # Expect list of bars with time and close
            series: Dict[str, float] = {}
            if isinstance(resp, dict):
                bars = resp.get("bars") or resp.get("data") or resp.get("items") or []
            else:
                bars = []
            for b in bars or []:
                t = b.get("time") or b.get("timestamp") or b.get("date")
                c = b.get("close") or b.get("c") or b.get("price")
                if t is None or c is None:
                    continue
                # Use date only portion for alignment
                tkey = str(t)[:10]
                try:
                    series[tkey] = float(c)
                except Exception:
                    continue
            symbol_to_series[p.symbol] = series
        except Exception:
            symbol_to_series[p.symbol] = {}

    # Union of all dates
    all_dates = set()
    for s in symbol_to_series.values():
        all_dates.update(s.keys())
    dates_sorted = sorted(all_dates)

    # Compute equity per date: sum(qty * close)
    equity: List[float] = []
    for d in dates_sorted:
        total = 0.0
        for p in snapshot.positions:
            price = symbol_to_series.get(p.symbol, {}).get(d)
            if price is not None:
                total += p.quantity * price
        total += sum(snapshot.cash.values()) if snapshot.cash else 0.0
        equity.append(total)

    lines["equity"] = equity

    # Benchmark optional
    if benchmark_symbol:
        try:
            path = f"/v1/instruments/{benchmark_symbol}/bars?timeframe=TIME_FRAME_D&interval.start_time={_iso(start)}&interval.end_time={_iso(end)}"
            resp = router.execute(ToolRequest(method="GET", path=path))
            bench_series: Dict[str, float] = {}
            bars = resp.get("bars") or resp.get("data") or resp.get("items") or [] if isinstance(resp, dict) else []
            for b in bars or []:
                t = b.get("time") or b.get("timestamp") or b.get("date")
                c = b.get("close") or b.get("c") or b.get("price")
                if t is None or c is None:
                    continue
                tkey = str(t)[:10]
                try:
                    bench_series[tkey] = float(c)
                except Exception:
                    continue
            bench: List[float] = []
            for d in dates_sorted:
                v = bench_series.get(d)
                bench.append(float(v) if v is not None else (bench[-1] if bench else 0.0))
            lines["benchmark"] = bench
        except Exception:
            pass

    return {"dates": dates_sorted, **lines}




