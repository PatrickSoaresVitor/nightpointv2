"""Bound identity write payloads before JSON parsing, including chunked bodies."""
import anyio
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.presentation.contracts import Problem
from .limits import LocalLimits


class IdentityBodyLimit:
    def __init__(self, app: ASGIApp, limits: LocalLimits | None = None, timeout: float = 2.0) -> None:
        self.app = app
        self.limits = limits or LocalLimits()
        self.timeout = timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        identity_path = scope.get("path") in {"/api/v1/session", "/api/v1/me/profile"} or scope.get("path", "").startswith("/api/v1/profiles/")
        if scope["type"] != "http" or not identity_path:
            await self.app(scope, receive, send)
            return

        async def reject(status: int, headers: dict[str, str] | None = None) -> None:
            from http import HTTPStatus
            problem = Problem(type="about:blank", title=HTTPStatus(status).phrase, status=status,
                detail="Request could not be served", correlation_id=scope["state"]["correlation_id"])
            await JSONResponse(problem.model_dump(), status_code=status, headers=headers,
                               media_type="application/problem+json")(scope, receive, send)
        try:
            client = scope.get("client")
            self.limits.check("request", client[0] if client else "unknown")
            if scope["method"] == "PUT":
                self.limits.check("write", "ingress:" + (client[0] if client else "unknown"))
        except HTTPException as error:
            await reject(error.status_code, dict(error.headers or {}))
            return
        if scope["method"] not in {"PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return
        if not self.limits.body_slots.acquire(blocking=False):
            await reject(503, {"Retry-After": "1"})
            return
        body = bytearray()
        try:
            with anyio.fail_after(self.timeout):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return
                    chunk = message.get("body", b"")
                    if len(body) + len(chunk) > 8192:
                        await reject(413)
                        return
                    body.extend(chunk)
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            await reject(408)
            return
        finally:
            self.limits.body_slots.release()

        delivered = False

        async def buffered() -> Message:
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, buffered, send)
