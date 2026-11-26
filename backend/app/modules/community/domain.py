from dataclasses import dataclass
from uuid import UUID


class HiddenComment(Exception): pass
class StaleComment(Exception): pass
class InteractionConflict(Exception): pass


def validate_comment(text: str) -> None:
    if (not text.strip() or len(text) > 1000 or any(
        ord(c) < 32 and c not in '\r\n\t' or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in text)):
        raise ValueError('Invalid comment')


@dataclass(frozen=True)
class Summary:
    likes: int
    participants: int
    liked: bool
    participating: bool


@dataclass(frozen=True)
class Comment:
    id: UUID
    event_id: UUID
    actor_id: UUID
    text: str
    version: int
    removed: bool
    removed_by: UUID | None

    def may_remove(self, actor: UUID, organizer: UUID) -> bool:
        return not self.removed and actor in {self.actor_id, organizer}

    def may_restore(self, actor: UUID) -> bool:
        return self.removed and self.removed_by == actor
