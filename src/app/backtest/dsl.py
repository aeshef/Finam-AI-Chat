from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class Rule:
    type: str
    params: Dict[str, Any]


@dataclass
class Strategy:
    symbol: str
    timeframe: str
    start: str
    end: str
    entry: Rule
    exit: Rule
    max_positions: int = 1


def parse_strategy(config: Dict[str, Any]) -> Strategy:
    # Defaults: daily timeframe, last 180 days if dates are missing
    start = config.get("start", "последние 180 дней")
    end = config.get("end", "сегодня")
    return Strategy(
        symbol=config["symbol"],
        timeframe=config.get("timeframe", "TIME_FRAME_D"),
        start=start,
        end=end,
        entry=Rule(type=config["entry"]["type"], params=config["entry"].get("params", {})),
        exit=Rule(type=config["exit"]["type"], params=config["exit"].get("params", {})),
        max_positions=int(config.get("max_positions", 1)),
    )




