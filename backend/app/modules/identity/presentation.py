from app.platform.telemetry import METRICS, measure
import re
import asyncio
from dataclasses import dataclass
from collections.abc import Callable, Awaitable
from datetime import datetime, timezone
import time
from typing import Annotated, Any, Self
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator
import anyio

from app.presentation.contracts import Problem
from .application import IdentityService
from .domain import HiddenResource, InvalidToken, MissingProfile, Profile, ProfileValues, ProfileChanges, ProviderUnavailable, StaleProfile, validate_profile_text, ExternalIdentity
from .ports import TokenVerifier
from .api import VerifiedActor
from .limits import LocalLimits as LocalLimits


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    nickname: str = Field(min_length=1, max_length=80)
    avatar_style: str | None = Field(default=None, min_length=1, max_length=64)
    avatar_seed: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("nickname", "avatar_style", "avatar_seed")
    @classmethod
    def valid_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        validate_profile_text(info.field_name or "", value)
        return value

    def values(self) -> ProfileValues:
        return ProfileValues(self.nickname, self.avatar_style, self.avatar_seed)


def patch_schema(schema: dict[str, Any]) -> None:
    schema["minProperties"] = 1
    schema["properties"]["nickname"] = {"type": "string", "minLength": 1, "maxLength": 80}


class ProfilePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, json_schema_extra=patch_schema)
    nickname: str | None = Field(default=None, min_length=1, max_length=80)
    avatar_style: str | None = Field(default=None, min_length=1, max_length=64)
    avatar_seed: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("nickname", "avatar_style", "avatar_seed")
    @classmethod
    def valid_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        validate_profile_text(info.field_name or "", value)
        return value

    @model_validator(mode="after")
    def nonempty(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Empty patch")
        return self

    def changes(self) -> ProfileChanges:
        return ProfileChanges({field: getattr(self, field) for field in self.model_fields_set})


class ProfileOutput(BaseModel):
    user_id: UUID
    nickname: str
    avatar_style: str | None
    avatar_seed: str | None
    version: int

    @classmethod
    def of(cls, profile: Profile) -> "ProfileOutput":
        return cls(user_id=profile.user_id, nickname=profile.values.nickname,
                   avatar_style=profile.values.avatar_style, avatar_seed=profile.values.avatar_seed,
                   version=profile.version)


class SessionOutput(BaseModel):
    user_id: UUID
    profile_complete: bool = True


@dataclass(frozen=True)
class IdentitySecurity:
    authenticated: Callable[..., Awaitable[ExternalIdentity]]
    actor: Callable[..., VerifiedActor]
    publisher: Callable[..., VerifiedActor]


def identity_security(verifier: TokenVerifier, service: IdentityService | None, limits: LocalLimits) -> IdentitySecurity:
    bearer = HTTPBearer(auto_error=False, scheme_name="FirebaseIDToken")

    async def authenticated(request: Request, _: Annotated[HTTPAuthorizationCredentials | None, Security(bearer)]) -> ExternalIdentity:
        headers = request.headers.getlist("authorization")
        challenge = HTTPException(401, headers={"WWW-Authenticate": "Bearer"})
        if len(headers) != 1:
            raise challenge
        match = re.fullmatch(r"(?i:Bearer) ([A-Za-z0-9_\-.]{1,8192})", headers[0])
        if match is None:
            raise challenge
        admission = time.monotonic()
        if not 0 <= limits.auth_wait_seconds <= .05:
            raise ValueError("Invalid bounded diagnostic admission")
        accepted = limits.auth_slots.acquire(blocking=False)
        while not accepted and time.monotonic()-admission < limits.auth_wait_seconds:
            await anyio.sleep(min(.001,max(0,limits.auth_wait_seconds-(time.monotonic()-admission))))
            accepted = limits.auth_slots.acquire(blocking=False)
        METRICS.observe("auth.admission", time.monotonic()-admission)
        if not accepted:
            limits.record_auth(None)
            METRICS.count("auth.rejected")
            METRICS.failure("auth_saturated")
            request.state.failure_category = "auth_saturated"
            raise HTTPException(503, headers={"Retry-After": "1"})
        start = time.monotonic()
        METRICS.count("auth.accepted")
        METRICS.gauge("auth.active", 1, delta=True)
        limiter = anyio.to_thread.current_default_thread_limiter()
        METRICS.gauge("threads.capacity", limiter.total_tokens)
        METRICS.gauge("threads.borrowed", limiter.borrowed_tokens)
        finished = 0.0
        def verify() -> ExternalIdentity:
            nonlocal finished
            METRICS.observe("auth.thread_wait",time.monotonic()-start)
            try:
                with measure("auth.verify"):
                    return verifier.verify(match.group(1))
            finally:finished=time.monotonic()
        worker=asyncio.create_task(anyio.to_thread.run_sync(verify,limiter=limits.auth_thread_limiter))
        def release_slot(done: asyncio.Task[ExternalIdentity]) -> None:
            # Keep physical verifier work within the admission budget after caller
            # cancellation. Retrieve deferred failures without exporting messages.
            if not done.cancelled():done.exception()
            if finished:METRICS.observe("auth.resume",time.monotonic()-finished)
            METRICS.observe("auth.slot_hold",time.monotonic()-start)
            limits.record_auth(time.monotonic()-start)
            limits.auth_slots.release()
            METRICS.gauge("auth.active",-1,delta=True)
            METRICS.observe("auth.total",time.monotonic()-start)
        try:
            identity = await asyncio.shield(worker)
            deadline = identity.expires_at.timestamp() if identity.expires_at is not None else datetime.now(timezone.utc).timestamp()+60
            request.state.identity_deadline = min(deadline,datetime.now(timezone.utc).timestamp()+60)
            return identity
        except InvalidToken:
            METRICS.failure("invalid_identity")
            request.state.failure_category = "invalid_identity"
            raise challenge from None
        except ProviderUnavailable:
            METRICS.failure("provider_unavailable")
            request.state.failure_category = "provider_unavailable"
            raise HTTPException(503) from None
        except asyncio.CancelledError:
            METRICS.failure("cancelled")
            request.state.failure_category="cancelled"
            raise
        finally:
            if worker.done():release_slot(worker)
            else:worker.add_done_callback(release_slot)

    def actor(identity: Annotated[ExternalIdentity, Depends(authenticated)]) -> VerifiedActor:
        verified = current_service().actor(identity)
        if verified is None:
            raise HTTPException(409)
        return verified

    def current_service() -> IdentityService:
        if service is None:
            raise HTTPException(503)
        return service

    def publisher(identity: Annotated[ExternalIdentity, Depends(authenticated)]) -> VerifiedActor:
        if not identity.email_verified or not identity.publication_authorized:
            raise HTTPException(403)
        verified = current_service().actor(identity)
        if verified is None:
            raise HTTPException(409)
        try:
            current_service().profile(verified.user_id, verified.user_id)
        except MissingProfile:
            raise HTTPException(409) from None
        return verified

    return IdentitySecurity(authenticated,actor,publisher)


def identity_router(verifier: TokenVerifier, service: IdentityService | None,
                    limits: LocalLimits, security: IdentitySecurity | None = None) -> APIRouter:
    problem: dict[str, Any] = {"description": "Sanitized Problem Details", "content": {
        "application/problem+json": {"schema": Problem.model_json_schema()}}}
    correlation_header: dict[str, Any] = {"X-Correlation-ID": {"schema": {"type": "string", "pattern": "^[0-9a-f]{32}$"}},
        "Cache-Control": {"schema": {"type": "string", "const": "no-store"}}}
    problem["headers"] = correlation_header
    router = APIRouter(prefix="/api/v1", tags=["identity"])
    profile_headers: dict[str, Any] = {**correlation_header, "ETag": {"description": "Quoted profile version",
        "schema": {"type": "string", "pattern": '^"[1-9][0-9]*"$'}}}

    def responses(*codes: int, profile: bool = True) -> dict[int | str, dict[str, Any]]:
        result: dict[int | str, dict[str, Any]] = {code: problem for code in (400,401,429,500,503,*codes)}
        result[401] = {**problem, "headers": {**correlation_header, "WWW-Authenticate": {"schema": {"type": "string", "const": "Bearer"}}}}
        result[429] = {**problem, "headers": {**correlation_header, "Retry-After": {"schema": {"type": "string"}}}}
        result[200] = {"description": "Success", "headers": profile_headers if profile else correlation_header}
        return result

    binding = security or identity_security(verifier,service,limits)
    authenticated, actor = binding.authenticated, binding.actor

    def current_service() -> IdentityService:
        if service is None:
            raise HTTPException(503)
        return service

    def read(acting: UUID, resource: UUID, response: Response) -> ProfileOutput:
        try:
            profile = current_service().profile(acting, resource)
        except (HiddenResource, MissingProfile):
            raise HTTPException(404) from None
        response.headers["ETag"] = f'"{profile.version}"'
        return ProfileOutput.of(profile)

    def update(acting: UUID, resource: UUID, body: ProfilePatch, response: Response, if_match: str) -> ProfileOutput:
        limits.check("write", str(acting))
        try:
            profile = current_service().update(acting, resource, body.changes(), int(if_match[1:-1]))
        except StaleProfile:
            raise HTTPException(412) from None
        except (HiddenResource, MissingProfile):
            raise HTTPException(404) from None
        response.headers["ETag"] = f'"{profile.version}"'
        return ProfileOutput.of(profile)

    @router.get("/session", response_model=SessionOutput, operation_id="identitySession", responses=responses(409, profile=False))
    def session(acting: Annotated[VerifiedActor, Depends(actor)]) -> SessionOutput:
        try:
            current_service().profile(acting.user_id, acting.user_id)
        except MissingProfile:
            raise HTTPException(409) from None
        return SessionOutput(user_id=acting.user_id)

    @router.get("/me/profile", response_model=ProfileOutput, operation_id="myProfile", responses=responses(404,409))
    def my_profile(acting: Annotated[VerifiedActor, Depends(actor)], response: Response) -> ProfileOutput:
        return read(acting.user_id, acting.user_id, response)

    @router.put("/me/profile", response_model=ProfileOutput, operation_id="provisionMyProfile",
                responses={**responses(408,413,422), 201: {"model": ProfileOutput, "description": "Profile created", "headers": profile_headers}})
    def provision(body: ProfileInput, identity: Annotated[ExternalIdentity, Depends(authenticated)], response: Response) -> ProfileOutput:
        profile, created = current_service().provision(identity, body.values())
        response.status_code = 201 if created else 200
        response.headers["ETag"] = f'"{profile.version}"'
        return ProfileOutput.of(profile)

    @router.patch("/me/profile", response_model=ProfileOutput, operation_id="updateMyProfile", responses=responses(404,409,412,413,408,422,428))
    def patch_me(body: ProfilePatch, acting: Annotated[VerifiedActor, Depends(actor)], response: Response,
                 if_match: Annotated[str, Header(pattern='^"[1-9][0-9]{0,9}"$')]) -> ProfileOutput:
        return update(acting.user_id, acting.user_id, body, response, if_match)

    # Private owner-only lookup; explicitly NOT a public card policy.
    @router.get("/profiles/{user_id}", response_model=ProfileOutput, operation_id="privateProfile", responses=responses(404,409,422))
    def private_profile(user_id: UUID, acting: Annotated[VerifiedActor, Depends(actor)], response: Response) -> ProfileOutput:
        return read(acting.user_id, user_id, response)

    @router.patch("/profiles/{user_id}", response_model=ProfileOutput, operation_id="updatePrivateProfile", responses=responses(404,409,412,413,408,422,428))
    def patch_private(user_id: UUID, body: ProfilePatch, acting: Annotated[VerifiedActor, Depends(actor)], response: Response,
                      if_match: Annotated[str, Header(pattern='^"[1-9][0-9]{0,9}"$')]) -> ProfileOutput:
        return update(acting.user_id, user_id, body, response, if_match)

    return router
