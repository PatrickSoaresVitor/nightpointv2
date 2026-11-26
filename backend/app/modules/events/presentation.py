from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Any, Self, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Response, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.modules.identity.api import VerifiedActor, ActorProvider
from app.presentation.contracts import Problem
from .application import EventService
from .domain import EventInput, Event, HiddenEvent, IdempotencyConflict, StaleEvent, EventStateConflict


class CreateEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1,max_length=120,strict=True)
    category_code: str = Field(pattern="^(street|jdm|premium|drift)$",strict=True)
    starts_at: datetime
    timezone: str = Field(min_length=1,max_length=64,strict=True)
    location_label: str = Field(min_length=1,max_length=200,strict=True)
    longitude: float = Field(ge=-180,le=180,allow_inf_nan=False,strict=True)
    latitude: float = Field(ge=-90,le=90,allow_inf_nan=False,strict=True)
    description: str | None = Field(default=None,min_length=1,max_length=2000,strict=True)
    visibility: Literal["listed", "owner_only"] = "listed"

    def value(self) -> EventInput:
        return EventInput(self.title,self.category_code,self.starts_at,self.timezone,self.location_label,self.longitude,self.latitude,self.description,self.visibility)

    @model_validator(mode="after")
    def valid(self) -> Self:
        self.value()
        return self


class EventOutput(BaseModel):
    id: UUID
    organizer_id: UUID
    title: str
    category_code: str
    starts_at: datetime
    timezone: str
    location_label: str
    longitude: float
    latitude: float
    description: str | None
    state: str = "published"
    visibility: str = "listed"
    version: int

    @classmethod
    def of(cls,event: Event) -> "EventOutput":
        return cls(id=event.id,organizer_id=event.organizer_id,title=event.values.title,category_code=event.values.category_code,
            starts_at=event.values.starts_at,timezone=event.values.timezone,location_label=event.values.location_label,
            longitude=event.values.longitude,latitude=event.values.latitude,description=event.values.description,version=event.version,
            state=event.state,visibility=event.values.visibility)


class OwnedEvents(BaseModel):
    items: list[EventOutput]
    next_offset: int | None


def actor_provider(actor: VerifiedActor) -> ActorProvider:
    def provide() -> VerifiedActor:
        return actor
    return provide


def business_errors(*codes: int) -> dict[int | str,dict[str,Any]]:
    headers: dict[str,Any] = {"X-Correlation-ID":{"schema":{"type":"string","pattern":"^[0-9a-f]{32}$"}},"Cache-Control":{"schema":{"type":"string","const":"no-store"}}}
    result: dict[int | str,dict[str,Any]] = {code:{"description":"Sanitized Problem Details","headers":dict(headers),
        "content":{"application/problem+json":{"schema":Problem.model_json_schema()}}} for code in (400,401,409,422,429,500,503,*codes)}
    result[401]["headers"]["WWW-Authenticate"] = {"schema":{"type":"string","const":"Bearer"}}
    result[429]["headers"]["Retry-After"] = {"schema":{"type":"string"}}
    return result


def success_headers() -> dict[str,Any]:
    return {"X-Correlation-ID":{"schema":{"type":"string","pattern":"^[0-9a-f]{32}$"}},
        "Cache-Control":{"schema":{"type":"string","const":"no-store"}},
        "ETag":{"schema":{"type":"string","pattern":'^"[1-9][0-9]*"$'}}}


def events_router(service: EventService | None, actor_dependency: Callable[...,VerifiedActor],
                  publisher_dependency: Callable[...,VerifiedActor]) -> APIRouter:
    router=APIRouter(prefix="/api/v1",tags=["events"])
    def current() -> EventService:
        if service is None: raise HTTPException(503)
        return service
    publisher = publisher_dependency

    @router.post("/events",response_model=EventOutput,status_code=201,operation_id="createEvent",
        responses={**business_errors(403,408,413),201:{"description":"Created or replayed creation (current representation)","headers":{**success_headers(),"Location":{"schema":{"type":"string"}}}}})
    def create(body: CreateEvent, actor: Annotated[VerifiedActor,Depends(publisher)],response: Response,
        idempotency_key: Annotated[UUID,Header(description="UUID scoped to actor and events.create.v1; repeated content returns the same resource")]) -> EventOutput:
        try:
            event=current().create(actor_provider(actor),idempotency_key,body.value())
        except IdempotencyConflict:
            raise HTTPException(409) from None
        response.headers["ETag"]=f'"{event.version}"'
        response.headers["Location"]="/api/v1/events/"+str(event.id)
        return EventOutput.of(event)

    @router.get("/me/events",response_model=OwnedEvents,operation_id="myEvents",
        responses={**business_errors(),200:{"description":"Owner-only bounded page; requery after mutation",
            "headers":{key:value for key,value in success_headers().items() if key!="ETag"}}})
    def owned(actor: Annotated[VerifiedActor,Depends(actor_dependency)],
              limit: Annotated[int,Query(ge=1,le=50)]=25,
              offset: Annotated[int,Query(ge=0,le=5000)]=0) -> OwnedEvents:
        rows=current().owned(actor_provider(actor),limit,offset)
        # Offset pages are bounded and not a snapshot: requery after changes.
        return OwnedEvents(items=[EventOutput.of(row) for row in rows[:limit]],
            next_offset=offset+limit if len(rows)>limit and offset+limit<=5000 else None)

    def manage(actor: VerifiedActor,event_id: UUID,body: CreateEvent | None,response: Response,if_match: str) -> EventOutput:
        try:
            event=current().update(actor_provider(actor),event_id,body.value() if body is not None else None,int(if_match[1:-1]))
        except HiddenEvent:raise HTTPException(404) from None
        except StaleEvent:raise HTTPException(412) from None
        except EventStateConflict:raise HTTPException(409) from None
        response.headers["ETag"]=f'"{event.version}"'
        return EventOutput.of(event)

    @router.put("/events/{event_id}",response_model=EventOutput,operation_id="updateEvent",
        responses={**business_errors(403,404,408,412,413,428),200:{"description":"Owner update","headers":success_headers()}})
    def update(event_id: UUID,body: CreateEvent,actor: Annotated[VerifiedActor,Depends(publisher)],response: Response,
        if_match: Annotated[str,Header(pattern='^"[1-9][0-9]{0,9}"$')]) -> EventOutput:
        return manage(actor,event_id,body,response,if_match)

    @router.post("/events/{event_id}/cancel",response_model=EventOutput,operation_id="cancelEvent",
        responses={**business_errors(404,408,412,413,428),200:{"description":"Owner cancellation without deleting history","headers":success_headers()}})
    def cancel(event_id: UUID,actor: Annotated[VerifiedActor,Depends(actor_dependency)],response: Response,
        if_match: Annotated[str,Header(pattern='^"[1-9][0-9]{0,9}"$')]) -> EventOutput:
        return manage(actor,event_id,None,response,if_match)

    @router.get("/events/{event_id}",response_model=EventOutput,operation_id="eventDetail",
        responses={**business_errors(404),200:{"description":"Authorized listed event","headers":success_headers()}})
    def detail(event_id: UUID,actor: Annotated[VerifiedActor,Depends(actor_dependency)],response: Response) -> EventOutput:
        try:
            event=current().detail(actor_provider(actor),event_id)
        except HiddenEvent:
            raise HTTPException(404) from None
        response.headers["ETag"]=f'"{event.version}"'
        return EventOutput.of(event)
    return router
