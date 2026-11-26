"""Local admission for the authorized backend slice; health and identity keep their budgets."""
from threading import BoundedSemaphore, Lock
import time
import anyio
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Scope, Receive, Send, Message
from app.presentation.contracts import Problem
from app.platform.telemetry import METRICS


class BusinessIngress:
    def __init__(self,app: ASGIApp) -> None:
        self.app=app
        self.lock=Lock()
        self.window=-1
        self.counts: dict[str,int]={}
        self.receivers=BoundedSemaphore(32)

    async def __call__(self,scope: Scope,receive: Receive,send: Send) -> None:
        path=scope.get("path","")
        if scope["type"]!="http" or not (path=="/api/v1/events" or path.startswith("/api/v1/events/") or path=="/api/v1/discovery/nearby"):
            await self.app(scope,receive,send)
            return
        async def reject(status: int) -> None:
            category = {429:"rate_limited",503:"body_saturated",413:"body_too_large",408:"body_timeout"}[status]
            scope["state"]["failure_category"] = category
            METRICS.failure(category)
            METRICS.count("body.rejected")
            from http import HTTPStatus
            body=Problem(type="about:blank",title=HTTPStatus(status).phrase,status=status,detail="Request could not be served",correlation_id=scope["state"]["correlation_id"])
            await JSONResponse(body.model_dump(),status_code=status,media_type="application/problem+json",headers={"Retry-After":"60"} if status==429 else None)(scope,receive,send)
        client=scope.get("client")
        key=client[0] if client else "unknown"
        with self.lock:
            window=int(time.monotonic()//60)
            if window!=self.window:
                self.counts.clear();self.window=window
            allowed=self.counts.get(key,0)<3600 and (key in self.counts or len(self.counts)<4096)
            if allowed:self.counts[key]=self.counts.get(key,0)+1
        if not allowed:
            await reject(429);return
        if scope["method"]!="POST":
            await self.app(scope,receive,send);return
        admitted = time.monotonic()
        acquired = self.receivers.acquire(blocking=False)
        METRICS.observe("http.admission",time.monotonic()-admitted)
        if not acquired:
            await reject(503);return
        METRICS.count("body.accepted")
        METRICS.gauge("body.active",1,delta=True)
        started=time.monotonic()
        body=bytearray()
        try:
            with anyio.fail_after(2):
                while True:
                    message=await receive()
                    if message["type"]=="http.disconnect":return
                    part=message.get("body",b"")
                    if len(body)+len(part)>8192:
                        await reject(413);return
                    body.extend(part)
                    if not message.get("more_body",False):break
        except TimeoutError:
            await reject(408);return
        finally:
            self.receivers.release()
            METRICS.gauge("body.active",-1,delta=True)
            METRICS.observe("http.body",time.monotonic()-started)
        delivered=False
        async def buffered() -> Message:
            nonlocal delivered
            if delivered:return await receive()
            delivered=True
            return {"type":"http.request","body":bytes(body),"more_body":False}
        await self.app(scope,buffered,send)
