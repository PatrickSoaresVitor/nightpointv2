"""Bounded, process-local performance counters. No request values or remote exporter."""
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
import math
from threading import Lock
import time
from typing import Any, ClassVar, cast

from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeout


PHASES = frozenset({
    "http.body", "http.admission", "http.dispatch", "http.logging", "http.serialization",
    "http.loop_lag", "auth.admission", "auth.thread_wait", "auth.verify", "auth.total",
    "auth.resume", "auth.slot_hold", "identity.lookup", "identity.sql", "db.acquire", "db.transaction", "db.attestation",
    "events.sql", "events.fetch", "events.project",
})
FAILURES = frozenset({
    "none", "auth_saturated", "body_saturated", "body_timeout", "body_too_large",
    "rate_limited", "invalid_identity", "provider_unavailable", "pool_timeout",
    "statement_cancelled", "statement_timeout", "query_cancelled", "lock_timeout", "connection_failure", "db_integrity",
    "db_permission", "db_other", "cancelled", "serialization", "application",
})
COUNTERS = frozenset({"body.accepted", "body.rejected", "auth.accepted", "auth.rejected", "db.connected"})
GAUGES = frozenset({"body.active", "auth.active", "threads.borrowed", "threads.capacity", "events.rows"})
BOUNDS_MS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1., 2., 5., 10., 20., 50., 100., 200., 500., 1000., 2000., 5000.)


@dataclass
class Histogram:
    count: int = 0
    total_ms: float = 0
    maximum_ms: float = 0
    buckets: list[int] = field(default_factory=lambda: [0] * (len(BOUNDS_MS) + 1))

    def observe(self, seconds: float) -> None:
        if not math.isfinite(seconds):
            return
        value = max(0., seconds * 1000)
        if not math.isfinite(value):
            return
        self.count += 1
        self.total_ms += value
        self.maximum_ms = max(self.maximum_ms, value)
        index = next((i for i, bound in enumerate(BOUNDS_MS) if value <= bound), len(BOUNDS_MS))
        self.buckets[index] += 1

    def snapshot(self) -> dict[str, Any]:
        target = math.ceil(self.count * .95)
        seen = 0
        upper = 0.
        for i, number in enumerate(self.buckets):
            seen += number
            if seen >= target:
                upper = BOUNDS_MS[i] if i < len(BOUNDS_MS) else self.maximum_ms
                break
        return {"count": self.count, "mean_ms": self.total_ms / self.count if self.count else 0,
                "max_ms": self.maximum_ms, "p95_bucket_upper_ms": upper, "buckets": list(self.buckets)}


class Telemetry:
    """Fixed names and histograms: memory is independent of traffic/user cardinality."""
    detail_enabled: ClassVar[bool] = True
    essential_phases: ClassVar[frozenset[str]] = frozenset({"http.loop_lag","auth.admission","auth.thread_wait","auth.verify","auth.resume","auth.slot_hold","auth.total"})

    def __init__(self) -> None:
        self.lock = Lock()
        self.histograms: dict[str, Histogram] = {}
        self.counters: dict[str, int] = {}
        self.gauges: dict[str, float] = {}
        self.maxima: dict[str, float] = {}
        self.failures: dict[str, int] = {}
        self.exception_kinds: dict[str, int] = {}

    def observe(self, name: str, seconds: float) -> None:
        if name not in PHASES:
            raise ValueError("Unknown telemetry phase")
        if not self.detail_enabled and name not in self.essential_phases:
            return
        with self.lock:
            histogram = self.histograms.get(name)
            if histogram is None:
                histogram = Histogram()
                self.histograms[name] = histogram
            histogram.observe(seconds)

    def count(self, name: str) -> None:
        if name not in COUNTERS:
            raise ValueError("Unknown telemetry counter")
        with self.lock:
            self.counters[name] = self.counters.get(name, 0) + 1

    def gauge(self, name: str, value: float, *, delta: bool = False) -> None:
        if name not in GAUGES or not math.isfinite(value):
            raise ValueError("Unknown or invalid telemetry gauge")
        with self.lock:
            current = self.gauges.get(name, 0) + value if delta else value
            self.gauges[name] = current
            self.maxima[name] = max(self.maxima.get(name, current), current)

    def failure(self, category: str) -> None:
        if category not in FAILURES:
            category = "application"
        with self.lock:
            self.failures[category] = self.failures.get(category, 0) + 1

    def exception(self, error: BaseException) -> None:
        kind = exception_kind(error)
        with self.lock:
            self.exception_kinds[kind] = self.exception_kinds.get(kind, 0) + 1

    def reset(self) -> None:
        with self.lock:
            self.histograms.clear()
            self.counters.clear()
            self.gauges.clear()
            self.maxima.clear()
            self.failures.clear()
            self.exception_kinds.clear()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {"phases": {k: v.snapshot() for k, v in self.histograms.items()},
                    "counters": dict(self.counters), "gauges": dict(self.gauges),
                    "maxima": dict(self.maxima), "failures": dict(self.failures),
                    "exception_kinds":dict(self.exception_kinds),
                    "histogram_bounds_ms": list(BOUNDS_MS), "scope": "process-local-aggregate"}


METRICS = Telemetry()


@contextmanager
def measure(name: str) -> Generator[None]:
    started = time.monotonic()
    try:
        yield
    finally:
        METRICS.observe(name, time.monotonic() - started)


def classify_failure(error: BaseException) -> str:
    """Never stringify the exception or export SQL/connection/request information."""
    if isinstance(error, BaseExceptionGroup):
        group = cast(BaseExceptionGroup[BaseException], error)
        return classify_failure(group.exceptions[0]) if group.exceptions else "application"
    if isinstance(error, PoolTimeout):
        return "pool_timeout"
    if isinstance(error, DBAPIError):
        state = getattr(error.orig, "sqlstate", None)
        if state == "57014":
            primary = getattr(getattr(error.orig,"diag",None),"message_primary",None)
            if primary == "canceling statement due to statement timeout":return "statement_timeout"
            if primary == "canceling statement due to user request":return "query_cancelled"
            return "statement_cancelled"
        if state == "55P03":
            return "lock_timeout"
        if state in {"08000", "08001", "08003", "08006", "08007", "08P01", "57P01", "57P02", "57P03"} or error.connection_invalidated:
            return "connection_failure"
        if state in {"23502", "23503", "23505", "23514"}:
            return "db_integrity"
        if state == "42501":
            return "db_permission"
        return "db_other"
    if isinstance(error, OSError):
        return "connection_failure"
    if isinstance(error, (KeyboardInterrupt, SystemExit)) or type(error).__name__ == "CancelledError":
        return "cancelled"
    if type(error).__name__ == "ResponseValidationError":
        return "serialization"
    return "application"


def exception_kind(error: BaseException) -> str:
    """Fixed diagnostics only; never export exception args, repr or traceback."""
    if isinstance(error,BaseExceptionGroup):
        group=cast(BaseExceptionGroup[BaseException],error)
        return exception_kind(group.exceptions[0]) if group.exceptions else "empty_group"
    if isinstance(error,RuntimeError):
        if error.args and isinstance(error.args[0],str) and error.args[0]=="No response returned.":
            return "asgi_no_response"
        return "runtime_other"
    if isinstance(error,PoolTimeout):return "pool_timeout"
    if isinstance(error,DBAPIError):return "database"
    if isinstance(error,OSError):return "os_error"
    module=type(error).__module__
    name=type(error).__name__
    if module.startswith("anyio") and name in {"EndOfStream","WouldBlock","BrokenResourceError","ClosedResourceError"}:
        return "anyio_"+name
    if name=="CancelledError":return "cancelled"
    if name=="ResponseValidationError":return "response_validation"
    return "other"
