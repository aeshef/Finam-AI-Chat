from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.app.backtest.dsl import Rule, Strategy
from src.app.backtest.indicators import sma, ema
from src.app.orchestration.router import ToolRouter, ToolRequest
from src.app.core.normalize import normalize_iso8601
from src.app.backtest.config import BacktestConfig


@dataclass
class Trade:
    time: str
    action: str  # buy/sell
    price: float
    quantity: int


@dataclass
class BTResult:
    equity_curve: List[float]
    trades: List[Trade]
    metrics: Dict[str, float]
    times: List[str]
    closes: List[float]
    opens: List[float]
    highs: List[float]
    lows: List[float]
    volumes: List[float]


def _fetch_bars(router: ToolRouter, symbol: str, timeframe: str, start: str, end: str) -> List[Dict[str, Any]]:
    path = f"/v1/instruments/{symbol}/bars?timeframe={timeframe}&interval.start_time={normalize_iso8601(start)}&interval.end_time={normalize_iso8601(end)}"
    resp = router.execute(ToolRequest(method="GET", path=path))
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for key in ("bars", "candles", "data", "items", "result"):
            v = resp.get(key)
            if isinstance(v, list):
                return v
            if isinstance(v, dict):
                for kk in ("items", "data"):
                    vv = v.get(kk)
                    if isinstance(vv, list):
                        return vv
        for v in resp.values():
            if isinstance(v, list) and v and isinstance(v[0], dict) and ("close" in v[0] or "timestamp" in v[0] or "time" in v[0]):
                return v
    return []


def _rule_signal(rule: Rule, context: Dict[str, List[float]], i: int) -> bool:
    if rule.type == "crossover":
        fast = ema(context["close"], int(rule.params.get("fast", 12)))
        slow = ema(context["close"], int(rule.params.get("slow", 26)))
        if fast[i] is None or slow[i] is None:
            return False
        return fast[i] > slow[i]
    if rule.type == "threshold":
        ref = float(rule.params.get("ref", 0))
        return context["close"][i] > ref
    return False


def _apply_commissions_slippage(price: float, qty: int, cfg: BacktestConfig, side: str) -> tuple[float, float]:
    slip = price * (cfg.slippage.bps / 10000.0)
    eff_price = price + slip if side == "buy" else price - slip
    notional = eff_price * qty
    fee = cfg.commissions.fixed_per_trade + cfg.commissions.percent_notional * notional
    return eff_price, fee


def _position_size(cash: float, price: float, cfg: BacktestConfig, vola_series: List[Optional[float]], i: int) -> int:
    if cfg.sizing.risk_fraction:
        vola = max(1e-8, (vola_series[i] or 0.01 * price) if i < len(vola_series) else 0.01 * price)
        target_risk_money = cash * cfg.sizing.risk_fraction
        qty = int(max(0.0, target_risk_money / vola))
        return qty
    return int(cash * cfg.sizing.fraction_of_cash / max(price, 1e-8))


def run_backtest(router: ToolRouter, strategy: Strategy, initial_cash: float = 100000.0, cfg: BacktestConfig | None = None) -> BTResult:
    cfg = cfg or BacktestConfig()
    bars = _fetch_bars(router, strategy.symbol, strategy.timeframe, strategy.start, strategy.end)
    if not bars:
        return BTResult(equity_curve=[initial_cash], trades=[], metrics={
            "final_equity": initial_cash,
            "return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "error": 1.0,  # flag for UI to show message
            "reason": "no_bars",
            "symbol": strategy.symbol,
            "timeframe": strategy.timeframe,
            "start": normalize_iso8601(strategy.start),
            "end": normalize_iso8601(strategy.end),
        }, times=[], closes=[], opens=[], highs=[], lows=[], volumes=[])
    def _num(x: Any) -> float:
        try:
            if isinstance(x, dict):
                x = x.get("value")
            return float(x) if x is not None else 0.0
        except Exception:
            return 0.0

    closes: List[float] = [_num(b.get("close") or b.get("c") or b.get("price")) for b in bars]
    opens: List[float] = [_num(b.get("open") or b.get("o")) for b in bars]
    highs: List[float] = [_num(b.get("high") or b.get("h")) for b in bars]
    lows: List[float] = [_num(b.get("low") or b.get("l")) for b in bars]
    volumes: List[float] = [_num(b.get("volume") or b.get("v")) for b in bars]
    times: List[str] = [str(b.get("time") or b.get("timestamp") or b.get("date")) for b in bars]
    context = {"close": closes}

    cash = initial_cash
    qty = 0
    trades: List[Trade] = []
    equity_curve: List[float] = []

    # Vola proxy (SMA of absolute returns)
    rets = [0.0] + [abs((closes[i] / closes[i-1] - 1.0)) if i > 0 and closes[i-1] else 0.0 for i in range(len(closes))]
    vola_series = sma(rets, window=max(2, cfg.sizing.vola_lookback))

    for i in range(len(closes)):
        price = closes[i]
        # exit first
        if qty > 0 and _rule_signal(strategy.exit, context, i):
            eff_price, fee = _apply_commissions_slippage(price, qty, cfg, side="sell")
            cash += qty * eff_price - fee
            trades.append(Trade(time=times[i], action="sell", price=price, quantity=qty))
            qty = 0
        # entry
        if qty == 0 and _rule_signal(strategy.entry, context, i):
            buy_qty = _position_size(cash, price, cfg, vola_series, i) if price > 0 else 0
            if buy_qty > 0:
                eff_price, fee = _apply_commissions_slippage(price, buy_qty, cfg, side="buy")
                cash -= buy_qty * eff_price + fee
                qty = buy_qty
                trades.append(Trade(time=times[i], action="buy", price=price, quantity=buy_qty))
        # optional pyramiding
        elif qty > 0 and cfg.pyramiding.enabled and cfg.pyramiding.max_adds > 0:
            last_buy = next((t for t in reversed(trades) if t.action == "buy"), None)
            if last_buy:
                threshold = last_buy.price * (1.0 + cfg.pyramiding.add_step_pct / 100.0)
                adds_done = sum(1 for t in trades if t.action == "buy") - 1
                if price >= threshold and adds_done < cfg.pyramiding.max_adds:
                    add_qty = _position_size(cash, price, cfg, vola_series, i)
                    if add_qty > 0:
                        eff_price, fee = _apply_commissions_slippage(price, add_qty, cfg, side="buy")
                        cash -= add_qty * eff_price + fee
                        qty += add_qty
                        trades.append(Trade(time=times[i], action="buy", price=price, quantity=add_qty))

        equity_curve.append(cash + qty * price)

    # close any open at last price
    if qty > 0 and closes:
        eff_price, fee = _apply_commissions_slippage(closes[-1], qty, cfg, side="sell")
        cash += qty * eff_price - fee
        trades.append(Trade(time=times[-1], action="sell", price=closes[-1], quantity=qty))
        qty = 0

    final_equity = cash
    ret = (final_equity / initial_cash - 1.0) * 100.0 if initial_cash > 0 else 0.0
    max_dd = 0.0
    peak = -1e18
    for v in equity_curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100.0 if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    metrics = {"final_equity": final_equity, "return_pct": ret, "max_drawdown_pct": max_dd}
    return BTResult(
        equity_curve=equity_curve,
        trades=trades,
        metrics=metrics,
        times=times,
        closes=closes,
        opens=opens,
        highs=highs,
        lows=lows,
        volumes=volumes,
    )




