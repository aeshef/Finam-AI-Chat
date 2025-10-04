from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from src.app.backtest.config import BacktestConfig
from src.app.backtest.executor import run_backtest, BTResult
from src.app.orchestration.router import ToolRequest, ToolRouter
from src.app.core.normalize import normalize_iso8601


@dataclass
class FoldResult:
    start: str
    end: str
    result: BTResult


def _fetch_bars_raw(router: ToolRouter, symbol: str, timeframe: str, start: str, end: str) -> List[Dict[str, Any]]:
    path = f"/v1/instruments/{symbol}/bars?timeframe={timeframe}&interval.start_time={normalize_iso8601(start)}&interval.end_time={normalize_iso8601(end)}"
    resp = router.execute(ToolRequest(method="GET", path=path))
    if isinstance(resp, dict):
        return resp.get("bars") or resp.get("data") or resp.get("items") or []
    return []


def rolling_cv(
    router: ToolRouter,
    strategy,
    initial_cash: float,
    cfg: BacktestConfig,
    window: int = 60,
    step: int = 20,
) -> Tuple[List[FoldResult], Dict[str, float]]:
    """Rolling cross-validation over historical bars.

    window, step in bars (e.g., days for TIME_FRAME_D).
    """
    bars = _fetch_bars_raw(router, strategy.symbol, strategy.timeframe, strategy.start, strategy.end)
    if not bars:
        return [], {"folds": 0}
    folds: List[FoldResult] = []
    for i in range(0, max(0, len(bars) - window + 1), step):
        seg = bars[i : i + window]
        if len(seg) < window:
            break
        s = seg[0].get("time") or seg[0].get("timestamp") or seg[0].get("date")
        e = seg[-1].get("time") or seg[-1].get("timestamp") or seg[-1].get("date")
        local = type(strategy)(
            symbol=strategy.symbol,
            timeframe=strategy.timeframe,
            start=str(s),
            end=str(e),
            entry=strategy.entry,
            exit=strategy.exit,
            max_positions=strategy.max_positions,
        )
        res = run_backtest(router, local, initial_cash=initial_cash, cfg=cfg)
        folds.append(FoldResult(start=str(s), end=str(e), result=res))
    # aggregate metrics
    if not folds:
        return folds, {"folds": 0}
    avg_ret = sum(f.result.metrics.get("return_pct", 0.0) for f in folds) / len(folds)
    avg_dd = sum(f.result.metrics.get("max_drawdown_pct", 0.0) for f in folds) / len(folds)
    return folds, {"folds": float(len(folds)), "avg_return_pct": avg_ret, "avg_max_drawdown_pct": avg_dd}


def bootstrap_returns(equity: List[float], num_samples: int = 1000) -> Dict[str, float]:
    """Naive bootstrap of simple daily returns to estimate mean CI."""
    if len(equity) < 2:
        return {}
    import random

    rets = [equity[i] / equity[i - 1] - 1.0 for i in range(1, len(equity)) if equity[i - 1] != 0]
    samples: List[float] = []
    for _ in range(num_samples):
        s = 1.0
        for _ in range(len(rets)):
            s *= 1.0 + random.choice(rets)
        samples.append((s - 1.0) * 100.0)
    samples.sort()
    lo = samples[int(0.05 * len(samples))]
    hi = samples[int(0.95 * len(samples)) - 1]
    return {"boot_mean_return_pct": sum(samples) / len(samples), "boot_ci_90_low": lo, "boot_ci_90_high": hi}


