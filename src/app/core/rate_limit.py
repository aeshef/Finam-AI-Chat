from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class TokenBucket:
    rate_per_sec: float
    burst: int

    def __post_init__(self) -> None:
        self._tokens: float = float(self.burst)
        self._last_refill: float = time.time()

    def _refill(self) -> None:
        now = time.time()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate_per_sec)
        self._last_refill = now

    def consume(self, amount: float = 1.0) -> float:
        """Consume tokens; returns wait time if we must delay, else 0.0."""
        self._refill()
        if self._tokens >= amount:
            self._tokens -= amount
            return 0.0
        needed = amount - self._tokens
        wait_sec = needed / self.rate_per_sec if self.rate_per_sec > 0 else 0.0
        # After waiting, assume tokens will be available
        self._tokens = max(0.0, self._tokens - amount)
        return max(0.0, wait_sec)


