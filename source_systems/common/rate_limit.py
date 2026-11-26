"""Limite de requisições por cliente (token bucket)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketLimiter:
    def __init__(
        self, per_minute: int, burst: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.rate_per_second = per_minute / 60
        self.capacity = float(burst)
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str) -> float:
        """Gasta uma ficha. Devolve 0 se liberado, ou os segundos de espera se não."""
        now = self._clock()
        with self._lock:
            bucket = self._buckets.setdefault(key, _Bucket(self.capacity, now))
            elapsed = now - bucket.updated_at
            bucket.tokens = min(self.capacity, bucket.tokens + elapsed * self.rate_per_second)
            bucket.updated_at = now
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return 0.0
            return (1 - bucket.tokens) / self.rate_per_second
