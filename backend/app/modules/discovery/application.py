from datetime import datetime, timezone
from app.modules.identity.api import ActorProvider
from app.modules.events.api import EventProjection, EventSummary, SearchSpec
from .domain import NearbyQuery, CursorPosition
from .ports import CursorCodec


class DiscoveryService:
    def __init__(self,projection: EventProjection,cursors: CursorCodec) -> None:
        self.projection=projection
        self.cursors=cursors

    def nearby(self,actor: ActorProvider,query: NearbyQuery,cursor: str | None) -> tuple[list[EventSummary],str | None]:
        binding=query.binding(actor().user_id)
        position=self.cursors.decode(cursor,binding) if cursor is not None else None
        snapshot=position.snapshot if position is not None else datetime.now(timezone.utc)
        search=SearchSpec(query.longitude,query.latitude,query.radius_m,query.from_ts,query.until_ts,query.category_code,snapshot,
            position.distance_mm if position else None,position.identifier if position else None)
        rows=self.projection.nearby(search,query.limit+1)
        page=rows[:query.limit]
        next_cursor=None
        if len(rows)>query.limit:
            last=page[-1]
            next_cursor=self.cursors.encode(CursorPosition(snapshot,last.distance_mm,last.id),binding)
        return page,next_cursor
