from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CATEGORIES = frozenset({"street", "jdm", "premium", "drift"})


class HiddenEvent(Exception): pass
class IdempotencyConflict(Exception): pass
class StaleEvent(Exception): pass
class EventStateConflict(Exception): pass


def text_value(value: str, maximum: int, *, multiline: bool = False) -> None:
    if not value.strip() or len(value) > maximum or any((ord(c) < 32 and not (multiline and c in '\r\n\t')) or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValueError("Invalid text")


@dataclass(frozen=True)
class EventInput:
    title: str
    category_code: str
    starts_at: datetime
    timezone: str
    location_label: str
    longitude: float
    latitude: float
    description: str | None = None
    visibility: str = "listed"

    def __post_init__(self) -> None:
        # Legacy unlisted is readable internally but never an API creation option.
        if self.visibility not in {"listed", "owner_only", "unlisted"}:
            raise ValueError("Invalid visibility")
        text_value(self.title,120)
        text_value(self.location_label,200)
        if self.category_code not in CATEGORIES:
            raise ValueError("Invalid category")
        if not isfinite(self.longitude) or not isfinite(self.latitude) or not -180 <= self.longitude <= 180 or not -90 <= self.latitude <= 90:
            raise ValueError("Invalid point")
        try:
            zone = ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid timezone") from None
        if self.starts_at.tzinfo is None or self.starts_at.utcoffset() != self.starts_at.astimezone(zone).utcoffset():
            raise ValueError("Explicit matching timezone required")
        if self.description is not None:
            text_value(self.description,2000,multiline=True)

    def canonical(self) -> dict[str, object]:
        return {"title":self.title,"category_code":self.category_code,"starts_at":self.starts_at.astimezone(timezone.utc).isoformat(),
            "timezone":self.timezone,"location_label":self.location_label,"longitude":self.longitude or 0.0,
            "latitude":self.latitude or 0.0,"description":self.description,
            **({"visibility":self.visibility} if self.visibility != "listed" else {})}


@dataclass(frozen=True)
class Event:
    id: UUID
    organizer_id: UUID
    values: EventInput
    version: int
    state: str = "published"
