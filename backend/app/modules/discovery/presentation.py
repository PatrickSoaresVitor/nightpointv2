from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Self, Any
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.modules.identity.api import VerifiedActor, ActorProvider
from .application import DiscoveryService
from .domain import NearbyQuery, InvalidCursor


class NearbyInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    longitude: float=Field(ge=-180,le=180,allow_inf_nan=False,strict=True)
    latitude: float=Field(ge=-90,le=90,allow_inf_nan=False,strict=True)
    radius_m: float=Field(ge=1,le=50000,allow_inf_nan=False,strict=True)
    from_ts: datetime
    until_ts: datetime
    category_code: str | None=Field(default=None,pattern="^(street|jdm|premium|drift)$")
    limit: int=Field(default=25,ge=1,le=50,strict=True)
    cursor: str | None=Field(default=None,min_length=1,max_length=2048)

    def query(self) -> NearbyQuery:
        return NearbyQuery(self.longitude,self.latitude,self.radius_m,self.from_ts,self.until_ts,self.category_code,self.limit)

    @model_validator(mode="after")
    def valid(self) -> Self:
        self.query();return self


class NearbyItem(BaseModel):
    id: UUID
    title: str
    category_code: str
    starts_at: datetime
    location_label: str
    distance_m: float
    version: int


class NearbyOutput(BaseModel):
    items: list[NearbyItem]
    next_cursor: str | None


def discovery_router(service: DiscoveryService | None,actor_dependency: Callable[...,VerifiedActor],errors: dict[int | str,dict[str,Any]]) -> APIRouter:
    router=APIRouter(prefix="/api/v1",tags=["discovery"])
    @router.post("/discovery/nearby",response_model=NearbyOutput,operation_id="nearbyEvents",responses=errors)
    def nearby(body: NearbyInput,actor: Annotated[VerifiedActor,Depends(actor_dependency)]) -> NearbyOutput:
        if service is None:raise HTTPException(503)
        def provide() -> VerifiedActor:return actor
        provider: ActorProvider=provide
        try:rows,cursor=service.nearby(provider,body.query(),body.cursor)
        except InvalidCursor:raise HTTPException(422) from None
        return NearbyOutput(items=[NearbyItem(id=r.id,title=r.title,category_code=r.category_code,starts_at=r.starts_at,
            location_label=r.location_label,distance_m=r.distance_mm/1000,version=r.version) for r in rows],next_cursor=cursor)
    return router
