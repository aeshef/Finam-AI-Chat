from __future__ import annotations

from typing import Any, Dict, List, Optional

import math

from src.app.orchestration.router import ToolRouter
from src.app.portfolio.aggregate import PortfolioSnapshot
from src.app.portfolio.equity import compute_equity_curve


def _pct_changes(series: List[float]) -> List[float]:
    rets: List[float] = []
    for i in range(1, len(series)):
        prev = series[i - 1]
        cur = series[i]
        if prev:
            rets.append(cur / prev - 1.0)
    return rets


def compute_risk_metrics(
    router: ToolRouter,
    snapshot: PortfolioSnapshot,
    days: int = 60,
    benchmark_symbol: Optional[str] = None,
) -> Dict[str, Any]:
    eq = compute_equity_curve(router, snapshot, days=days, benchmark_symbol=benchmark_symbol)
    eq_series = eq.get("equity", [])
    bench_series = eq.get("benchmark")
    rets = _pct_changes(eq_series)
    metrics: Dict[str, Any] = {}
    if rets:
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / len(rets)
        vol = math.sqrt(var) * math.sqrt(252.0)  # annualized
        metrics["volatility_ann"] = vol * 100.0
        metrics["mean_daily_return_pct"] = mean * 100.0
        # VaR/ES 95%
        s = sorted(rets)
        idx = max(0, int(0.05 * len(s)) - 1)
        var95 = s[idx]
        es95 = sum(s[: idx + 1]) / (idx + 1) if idx >= 0 else s[0]
        metrics["VaR_95_pct"] = var95 * 100.0
        metrics["ES_95_pct"] = es95 * 100.0
    if bench_series:
        b_rets = _pct_changes(bench_series)
        n = min(len(rets), len(b_rets))
        if n > 1:
            pr = rets[-n:]
            br = b_rets[-n:]
            mean_p = sum(pr) / n
            mean_b = sum(br) / n
            cov = sum((pr[i] - mean_p) * (br[i] - mean_b) for i in range(n)) / n
            var_b = sum((br[i] - mean_b) ** 2 for i in range(n)) / n
            beta = (cov / var_b) if var_b > 0 else None
            te = math.sqrt(sum((pr[i] - br[i]) ** 2 for i in range(n)) / n)
            metrics["beta_vs_benchmark"] = beta
            metrics["tracking_error_ann"] = te * math.sqrt(252.0) * 100.0
    return {"dates": eq.get("dates"), "equity": eq_series, "benchmark": bench_series, "risk": metrics}


def compute_exposures(snapshot: PortfolioSnapshot) -> Dict[str, Any]:
    """Compute simple exposures: weights by sector and by symbol."""
    total = snapshot.equity if snapshot.equity else sum(p.market_value for p in snapshot.positions)
    by_sector: Dict[str, float] = {}
    by_symbol: Dict[str, float] = {}
    for p in snapshot.positions:
        w = (p.market_value / total) if total else 0.0
        by_symbol[p.symbol] = w
        by_sector[p.sector] = by_sector.get(p.sector, 0.0) + w
    return {"by_sector": by_sector, "by_symbol": by_symbol}


