from uuid import UUID
from contextlib import contextmanager
from collections.abc import Generator
from app.modules.identity.api import ActorProvider
from .domain import Event, EventInput, HiddenEvent
from .ports import EventRepository, ChangePublisher
from .api import EventContext, InaccessibleEvent
import logging


class EventService:
    def __init__(self, repository: EventRepository, publisher: ChangePublisher | None = None) -> None:
        self.repository = repository
        self.publisher = publisher

    @contextmanager
    def hold(self, actor: UUID, identifier: UUID) -> Generator[EventContext]:
        try:
            with self.repository.guard(actor, identifier) as event:
                yield EventContext(event.id, event.organizer_id, event.state, event.version)
        except HiddenEvent: raise InaccessibleEvent() from None

    def create(self, actor: ActorProvider, key: UUID, values: EventInput) -> Event:
        event, created = self.repository.create(actor().user_id,key,values)
        # Repository returns only after its SQL transaction committed successfully.
        if created and self.publisher is not None:
            try:self.publisher.publish(event.id,event.version)
            except Exception:logging.getLogger("nightpoint").warning("notification_unavailable")
        return event

    def detail(self, actor: ActorProvider, identifier: UUID) -> Event:
        acting = actor()
        event = self.repository.detail(identifier, acting.user_id)
        if event is None:
            raise HiddenEvent()
        return event

    def update(self, actor: ActorProvider, identifier: UUID, values: EventInput | None, version: int) -> Event:
        event = self.repository.update(actor().user_id, identifier, values, version)
        if self.publisher is not None:
            try:self.publisher.publish(event.id,event.version)
            except Exception:logging.getLogger("nightpoint").warning("notification_unavailable")
        return event

    def owned(self, actor: ActorProvider, limit: int, offset: int) -> list[Event]:
        if not 1 <= limit <= 50 or not 0 <= offset <= 5000:
            raise ValueError("Invalid listing bounds")
        return self.repository.owned(actor().user_id,limit+1,offset)
