from threading import BoundedSemaphore, Lock
import time
from anyio import CapacityLimiter
from fastapi import HTTPException


class LocalLimits:
    """Bounded per-process counters; no actor, token or request stored in telemetry."""
    def __init__(self, requests: int = 60, writes: int = 20, capacity: int = 4096) -> None:
        self.requests, self.writes, self.capacity = requests, writes, capacity
        self._buckets: dict[tuple[str, str], int] = {}
        self._window = -1
        self._lock = Lock()
        self.auth_slots = BoundedSemaphore(4)
        # Only explicit test_limits composition may override these local diagnostics.
        # create_app rejects that composition outside NP_ENV=test.
        self.auth_wait_seconds = 0.0
        self.auth_thread_limiter: CapacityLimiter | None = None
        self.body_slots = BoundedSemaphore(8)
        self.auth_calls = 0
        self.auth_saturation = 0
        self.auth_seconds = 0.0

    def check(self, kind: str, key: str) -> None:
        window = int(time.monotonic() // 60)
        with self._lock:
            if self._window != window:
                self._buckets.clear()
                self._window = window
            bucket = (kind, key)
            count = self._buckets.get(bucket, 0)
            if count >= (self.writes if kind == "write" else self.requests) or (
                bucket not in self._buckets and len(self._buckets) >= self.capacity):
                raise HTTPException(429, headers={"Retry-After": "60"})
            self._buckets[bucket] = count + 1

    def record_auth(self, seconds: float | None) -> None:
        with self._lock:
            if seconds is None:
                self.auth_saturation += 1
            else:
                self.auth_calls += 1
                self.auth_seconds += seconds
