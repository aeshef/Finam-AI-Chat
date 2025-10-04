from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CommissionModel:
    fixed_per_trade: float = 0.0           # абсолютная комиссия за сделку
    percent_notional: float = 0.0          # доля от оборота, напр. 0.0005 = 5 б.п.


@dataclass
class SlippageModel:
    bps: float = 0.0                       # проскальзывание в б.п. от цены (0.0 = нет)


@dataclass
class SizingModel:
    fraction_of_cash: float = 1.0          # доля доступного кэша
    risk_fraction: Optional[float] = None  # риск на сделку (доля от equity), если задан — приоритетнее
    vola_lookback: int = 20                # окна для таргетирования волатильности (дней)


@dataclass
class PyramidingModel:
    enabled: bool = False
    max_adds: int = 0
    add_step_pct: float = 0.0              # через какой прирост/просадку добавлять (в %)


@dataclass
class BacktestConfig:
    commissions: CommissionModel = field(default_factory=CommissionModel)
    slippage: SlippageModel = field(default_factory=SlippageModel)
    sizing: SizingModel = field(default_factory=SizingModel)
    pyramiding: PyramidingModel = field(default_factory=PyramidingModel)


