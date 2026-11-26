"""Explicit synthetic local composition. Never selected by the normal API factory."""
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import secrets
from threading import Lock
import time
from typing import Literal, cast
from urllib.parse import urlsplit
import os

import anyio
from fastapi import FastAPI, Header, HTTPException, Response, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.cors import CORSMiddleware

from app.application.health import ReadinessProbe
from app.bootstrap import create_app
from app.modules.events.realtime import StreamSettings
from app.modules.identity.domain import ExternalIdentity, InvalidToken
from app.platform.config import Settings, load_settings


class SessionCapacity(Exception): pass


class SyntheticSessions:
    """Bounded opaque nonces for fictional personas, with expiry and revocation."""
    def __init__(self, *, ttl: float = 900, capacity: int = 32, clock: Callable[[],float] = time.time) -> None:
        if not 0 < ttl <= 900 or not 1 <= capacity <= 32:
            raise ValueError("Invalid bounded synthetic sessions")
        self.ttl, self.capacity, self.clock = ttl, capacity, clock
        self._sessions: dict[str,tuple[str,float]] = {}
        self._lock = Lock()

    def issue(self, persona: str) -> str:
        if persona not in {'participant-a','participant-b'}:
            raise ValueError('Unknown synthetic persona')
        with self._lock:
            now=self.clock()
            self._sessions={key:value for key,value in self._sessions.items() if value[1]>now}
            if len(self._sessions)>=self.capacity:raise SessionCapacity()
            token=secrets.token_urlsafe(32)
            self._sessions[token]=(persona,now+self.ttl)
            return token

    def verify(self, token: str) -> ExternalIdentity:
        with self._lock:
            item=self._sessions.get(token)
            if item is None:raise InvalidToken()
            persona,expires=item
            if expires<=self.clock():
                self._sessions.pop(token,None)
                raise InvalidToken()
            # This is fixture eligibility, never evidence about a real person.
            return ExternalIdentity('nightpoint-synthetic-demo',persona,
                datetime.fromtimestamp(expires,timezone.utc),email_verified=True,publication_authorized=True)

    def revoke(self, token: str) -> None:
        with self._lock:self._sessions.pop(token,None)

    def close(self) -> None:
        with self._lock:self._sessions.clear()


class DemoEntry(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    persona: Literal['participant-a','participant-b']


class DemoToken(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal['Bearer'] = 'Bearer'
    expires_in: int = 900
    mode: Literal['synthetic'] = 'synthetic'


def local_origin(origin: str) -> str:
    try:
        parsed=urlsplit(origin)
        if (parsed.scheme!='http' or parsed.hostname not in {'127.0.0.1','localhost','::1'}
            or parsed.username is not None or parsed.password is not None or parsed.path or parsed.query
            or parsed.fragment or parsed.port is None or not 1<=parsed.port<=65535):
            raise ValueError()
    except ValueError:raise ValueError('Explicit loopback web origin required') from None
    return origin


def create_demo_app(settings: Settings, probe: ReadinessProbe | None = None, *,
                    web_origin: str = 'http://127.0.0.1:5173') -> FastAPI:
    if settings.environment!='test':
        raise ValueError('Synthetic identity requires the disposable test environment')
    origin=local_origin(web_origin)
    sessions=SyntheticSessions()
    application=create_app(settings,probe,test_verifier=sessions,test_streams=StreamSettings(.5,1,5))
    original=application.router.lifespan_context
    readiness=probe if probe is not None else cast(ReadinessProbe,application.state.database)

    @asynccontextmanager
    async def lifespan(instance: FastAPI) -> AsyncGenerator[None]:
        async with original(instance):
            try:
                deadline=time.monotonic()+30
                while not await anyio.to_thread.run_sync(readiness.ready):
                    if time.monotonic()>=deadline:
                        raise RuntimeError('Synthetic demo requires a ready attested database')
                    await anyio.sleep(.25)
                yield
            finally:sessions.close()
    application.router.lifespan_context=lifespan
    application.add_middleware(CORSMiddleware,allow_origins=[origin],allow_credentials=False,
        allow_methods=['GET','POST','PUT','PATCH','OPTIONS'],
        allow_headers=['Authorization','Content-Type','Idempotency-Key','If-Match','Last-Event-ID','X-Correlation-ID'],
        expose_headers=['ETag','X-Correlation-ID','Location'],max_age=60)

    @application.post('/api/v1/demo/session',response_model=DemoToken,operation_id='syntheticSession')
    def enter(body: DemoEntry) -> DemoToken:
        try:token=sessions.issue(body.persona)
        except SessionCapacity:raise HTTPException(429,headers={'Retry-After':'60'}) from None
        return DemoToken(access_token=token)

    @application.post('/api/v1/demo/logout',status_code=204,operation_id='syntheticLogout')
    def leave(request: Request,authorization: str = Header(default='')) -> Response:
        if len(request.headers.getlist('authorization')) != 1:
            raise HTTPException(401,headers={'WWW-Authenticate':'Bearer'})
        scheme,_,token=authorization.partition(' ')
        if scheme.lower()!='bearer':raise HTTPException(401,headers={'WWW-Authenticate':'Bearer'})
        try:sessions.verify(token)
        except InvalidToken:raise HTTPException(401,headers={'WWW-Authenticate':'Bearer'}) from None
        sessions.revoke(token)
        return Response(status_code=204)

    application.state.synthetic_sessions=sessions
    return application


def app_factory() -> FastAPI:
    return create_demo_app(load_settings(),web_origin=os.environ.get('NP_DEMO_WEB_ORIGIN','http://127.0.0.1:5173'))
