"""Authorized read projection contract, independent of persistence and private models."""
from dataclasses import dataclass
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol
from uuid import UUID

__all__ = ["SearchSpec", "EventSummary", "EventProjection", "EventContext", "EventAccess", "InaccessibleEvent"]


class InaccessibleEvent(Exception): pass


@dataclass(frozen=True)
class EventContext:
    id: UUID
    owner_id: UUID
    state: str
    version: int


class EventAccess(Protocol):
    def hold(self, actor: UUID, identifier: UUID) -> AbstractContextManager[EventContext]: ...


@dataclass(frozen=True)
class SearchSpec:
    longitude: float
    latitude: float
    radius_m: float
    from_ts: datetime
    until_ts: datetime
    category_code: str | None
    snapshot: datetime
    after_mm: int | None = None
    after_id: UUID | None = None


@dataclass(frozen=True)
class EventSummary:
    id: UUID
    title: str
    category_code: str
    starts_at: datetime
    location_label: str
    distance_mm: int
    version: int


class EventProjection(Protocol):
    def nearby(self, search: SearchSpec, limit: int) -> list[EventSummary]: ...
