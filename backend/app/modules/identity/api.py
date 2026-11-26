"""The complete public identity contract. No profile, provider or persistence types."""
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

__all__ = ["VerifiedActor", "ActorProvider"]


@dataclass(frozen=True)
class VerifiedActor:
    user_id: UUID


class ActorProvider(Protocol):
    def __call__(self) -> VerifiedActor: ...
