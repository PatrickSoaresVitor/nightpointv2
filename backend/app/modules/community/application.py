import logging
from typing import Literal
from uuid import UUID
from app.modules.identity.api import ActorProvider
from app.modules.events.api import EventAccess, EventContext
from .domain import Summary, Comment, HiddenComment, InteractionConflict, validate_comment
from .ports import CommunityRepository, InvalidationPublisher


class CommunityService:
    def __init__(self, repository: CommunityRepository, access: EventAccess, publisher: InvalidationPublisher) -> None:
        self.repository, self.access, self.publisher = repository, access, publisher

    def _notify(self, event_id: UUID) -> None:
        try: self.publisher.invalidate(event_id)
        except Exception: logging.getLogger('nightpoint').warning('notification_unavailable')

    def summary(self, actor: ActorProvider, event_id: UUID) -> Summary:
        acting = actor().user_id
        with self.access.hold(acting, event_id): return self.repository.summary(acting, event_id)

    def reaction(self, actor: ActorProvider, event_id: UUID, kind: Literal['like','participation'], active: bool) -> None:
        acting = actor().user_id
        with self.access.hold(acting, event_id) as event:
            if active and event.state != 'published': raise InteractionConflict()
            self.repository.reaction(acting, event_id, kind, active)
        self._notify(event_id)

    def comments(self, actor: ActorProvider, event_id: UUID, include_removed: bool, limit: int, offset: int) -> tuple[EventContext,list[Comment]]:
        if not 1 <= limit <= 50 or not 0 <= offset <= 5000: raise ValueError('Invalid bounds')
        acting = actor().user_id
        with self.access.hold(acting, event_id) as event:
            return event,self.repository.comments(acting,event_id,include_removed,limit+1,offset)

    def create_comment(self, actor: ActorProvider, event_id: UUID, key: UUID, text: str) -> tuple[EventContext,Comment,bool]:
        validate_comment(text)
        acting = actor().user_id
        with self.access.hold(acting, event_id) as event:
            comment,created = self.repository.create_comment(acting,event_id,key,text,event.state=='published')
        if created: self._notify(event_id)
        return event,comment,created

    def comment(self, actor: ActorProvider, event_id: UUID, identifier: UUID) -> tuple[EventContext,Comment]:
        acting = actor().user_id
        with self.access.hold(acting,event_id) as event:
            comment = self.repository.comment(acting,event_id,identifier)
            if comment is None: raise HiddenComment()
            return event,comment

    def visibility(self, actor: ActorProvider, event_id: UUID, identifier: UUID, removed: bool, version: int) -> tuple[EventContext,Comment]:
        acting = actor().user_id
        with self.access.hold(acting,event_id) as event:
            comment = self.repository.visibility(acting,event.owner_id,event_id,identifier,removed,version)
        self._notify(event_id)
        return event,comment
