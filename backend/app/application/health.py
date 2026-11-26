from typing import Protocol


class ReadinessProbe(Protocol):
    def ready(self) -> bool: ...


def is_ready(probe: ReadinessProbe) -> bool:
    """A failed dependency must not affect liveness, but must fail readiness."""
    return probe.ready()
