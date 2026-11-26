from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from uuid import UUID


class InvalidCursor(ValueError): pass


@dataclass(frozen=True)
class NearbyQuery:
    longitude: float
    latitude: float
    radius_m: float
    from_ts: datetime
    until_ts: datetime
    category_code: str | None = None
    limit: int = 25

    def __post_init__(self) -> None:
        if not isfinite(self.longitude) or not isfinite(self.latitude) or not -180<=self.longitude<=180 or not -90<=self.latitude<=90:
            raise ValueError("Invalid origin")
        if not isfinite(self.radius_m) or not 1<=self.radius_m<=50000 or not 1<=self.limit<=50:
            raise ValueError("Invalid limits")
        if self.from_ts.tzinfo is None or self.until_ts.tzinfo is None or not timedelta(0)<self.until_ts-self.from_ts<=timedelta(days=31):
            raise ValueError("Invalid interval")
        if self.category_code is not None and self.category_code not in {"street","jdm","premium","drift"}:
            raise ValueError("Invalid category")

    def binding(self,actor: UUID) -> dict[str,object]:
        return {"catalog_policy":"published-listed-unchanged-v2","actor":str(actor),"longitude":self.longitude or 0.0,"latitude":self.latitude or 0.0,
            "radius_m":float(self.radius_m),"from_ts":self.from_ts.astimezone(timezone.utc).isoformat(),
            "until_ts":self.until_ts.astimezone(timezone.utc).isoformat(),"category_code":self.category_code,"limit":self.limit}


@dataclass(frozen=True)
class CursorPosition:
    snapshot: datetime
    distance_mm: int
    identifier: UUID
