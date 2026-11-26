from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
import json
from queue import Empty
import time
from typing import Annotated
from uuid import UUID
import anyio
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse
from app.modules.identity.api import VerifiedActor
from app.platform.realtime import EventBus, ConnectionLimit
from .application import EventService
from .domain import HiddenEvent
from .presentation import actor_provider, business_errors, success_headers


@dataclass(frozen=True)
class StreamSettings:
    heartbeat: float = 5.0
    reconcile: float = 10.0
    lease: float = 60.0

    def __post_init__(self) -> None:
        if not 0.01<=self.heartbeat<=30 or not self.heartbeat<=self.reconcile<=30 or not 0.05<=self.lease<=60:
            raise ValueError("Invalid local stream budget")


def frame(kind: str,version: int | None=None) -> str:
    data={} if version is None else {"version":version}
    return (f"id: {version}\n" if version is not None else "")+f"event: {kind}\ndata: "+json.dumps(data,separators=(",",":"))+"\n\n"


def updates_router(service: EventService | None,actor_dependency: Callable[...,VerifiedActor],bus: EventBus,settings: StreamSettings) -> APIRouter:
    router=APIRouter(prefix="/api/v1",tags=["event-updates"])
    headers={k:v for k,v in success_headers().items() if k!="ETag"}
    @router.get("/events/{event_id}/updates",response_class=StreamingResponse,operation_id="eventUpdates",
        responses={**business_errors(404),200:{"description":"Authorized invalidations; always reconcile via REST",
            "headers":headers,"content":{"text/event-stream":{"schema":{"type":"string"}}}}})
    async def updates(event_id: UUID,request: Request,actor: Annotated[VerifiedActor,Depends(actor_dependency)],
        last_event_id: Annotated[str | None,Header(pattern="^(0|[1-9][0-9]{0,18})$",description="Resume hint only; reconnect always emits resync")] = None) -> StreamingResponse:
        if service is None:raise HTTPException(503)
        current_service=service
        provider=actor_provider(actor)
        def detail() -> int:return current_service.detail(provider,event_id).version
        try:version=await anyio.to_thread.run_sync(detail)
        except HiddenEvent:raise HTTPException(404) from None
        expires=min(float(request.state.identity_deadline),time.time()+settings.lease)
        if expires<=time.time():raise HTTPException(401,headers={"WWW-Authenticate":"Bearer"})
        try:subscription=bus.subscribe(event_id,actor.user_id,version)
        except ConnectionLimit:raise HTTPException(429,headers={"Retry-After":"5"}) from None
        async def stream() -> AsyncIterator[str]:
            try:
                yield frame("resync",version)
                delivered_version=version
                next_heartbeat=time.monotonic()+settings.heartbeat
                next_reconcile=time.monotonic()+settings.reconcile
                while not subscription.closed:
                    if time.time()>=expires:
                        yield frame("session-expired")
                        break
                    if await request.is_disconnected():break
                    try:change=subscription.messages.get_nowait()
                    except Empty:change=None
                    current=time.monotonic()
                    if change is not None or current>=next_heartbeat or current>=next_reconcile:
                        try:latest=await anyio.to_thread.run_sync(detail)
                        except HiddenEvent:break
                        if time.time()>=expires:
                            yield frame("session-expired")
                            break
                        if change is not None and (latest>delivered_version or change.kind=="resync"):
                            delivered_version=max(delivered_version,latest)
                            yield frame(change.kind,delivered_version)
                        if current>=next_reconcile:
                            delivered_version=max(delivered_version,latest)
                            yield frame("resync",delivered_version)
                            next_reconcile=current+settings.reconcile
                        if current>=next_heartbeat:
                            yield ": heartbeat\n\n"
                            next_heartbeat=current+settings.heartbeat
                    await anyio.sleep(0.02)
            finally:bus.unsubscribe(subscription)
        return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-store","X-Accel-Buffering":"no"},
            background=BackgroundTask(bus.unsubscribe,subscription))
    return router
