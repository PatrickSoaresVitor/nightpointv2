from dataclasses import dataclass
import hashlib
import json
from uuid import UUID
from typing import Literal


class HiddenVehicle(Exception): pass
class StaleVehicle(Exception): pass
class VehicleConflict(Exception): pass


def valid_text(value: str, maximum: int) -> None:
    if (not value.strip() or len(value) > maximum or
        any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise ValueError('Invalid vehicle text')


@dataclass(frozen=True)
class VehicleInput:
    brand: str
    model: str
    year: int | None = None
    color: str | None = None
    category: Literal['car', 'motorcycle', 'truck', 'other'] = 'car'
    primary: bool = False
    archived: bool = False

    def __post_init__(self) -> None:
        valid_text(self.brand, 80)
        valid_text(self.model, 120)
        if self.color is not None: valid_text(self.color, 60)
        if self.year is not None and (type(self.year) is not int or not 1900 <= self.year <= 2100):
            raise ValueError('Invalid year')
        if self.category not in {'car', 'motorcycle', 'truck', 'other'}:
            raise ValueError('Invalid category')
        if type(self.primary) is not bool or type(self.archived) is not bool or self.primary and self.archived:
            raise ValueError('Archived vehicle cannot be primary')

    def canonical(self) -> dict[str, object]:
        return {'brand': self.brand, 'model': self.model, 'year': self.year, 'color': self.color,
                'category': self.category, 'primary': self.primary, 'archived': self.archived}

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.canonical(), sort_keys=True, ensure_ascii=False,
                                        separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class Vehicle:
    id: UUID
    owner_id: UUID
    values: VehicleInput
    version: int


@dataclass(frozen=True)
class VehicleRevision:
    version: int
    kind: str
    values: VehicleInput
