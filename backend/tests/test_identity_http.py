from collections.abc import Iterator
import asyncio
from typing import cast
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest
from starlette.types import Message, Receive, Scope, Send

from app.bootstrap import create_app
from app.modules.identity.presentation import LocalLimits
from app.modules.identity.body_limit import IdentityBodyLimit
from tests.identity_fakes import FakeVerifier, MemoryRepository
from tests.test_foundation import Probe, settings


@pytest.fixture
def client() -> Iterator[httpx.Client]:
    app = create_app(settings(), Probe(True), identity_test=(FakeVerifier(), MemoryRepository()))
    with TestClient(app) as transport:
        yield cast(httpx.Client, transport)


def headers(actor: str = "actor-a") -> dict[str, str]:
    return {"Authorization": "Bearer " + actor}


@pytest.mark.parametrize("value", [None, "", "Basic abc", "Bearer", "Bearer a b", "Bearer bad-token", "Bearer " + "a" * 8193])
def test_safe_bearer_and_invalid_token(client: httpx.Client, value: str | None) -> None:
    response = client.get("/api/v1/session", headers={} if value is None else {"Authorization": value})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["content-type"] == "application/problem+json"
    assert "bad-token" not in response.text


def test_duplicate_authorization_refused(client: httpx.Client) -> None:
    assert client.get("/api/v1/session", headers=[("Authorization", "Bearer actor-a"),
        ("Authorization", "Bearer actor-b")]).status_code == 401


def test_provision_recovery_idempotence_and_conditional_patch(client: httpx.Client) -> None:
    assert client.get("/api/v1/session", headers=headers()).status_code == 409
    assert client.get("/api/v1/me/profile", headers=headers()).status_code == 409
    first = client.put("/api/v1/me/profile", headers=headers(), json={"nickname": "Synthetic"})
    assert first.status_code == 201 and first.headers["etag"] == '"1"'
    repeated = client.put("/api/v1/me/profile", headers=headers(), json={"nickname": "Ignored retry"})
    assert repeated.status_code == 200 and repeated.json() == first.json()
    assert client.get("/api/v1/session", headers=headers()).json()["user_id"] == first.json()["user_id"]
    assert set(first.json()) == {"user_id", "nickname", "avatar_style", "avatar_seed", "version"}
    assert client.patch("/api/v1/me/profile", headers=headers(), json={"nickname": "Next"}).status_code == 428
    patched = client.patch("/api/v1/me/profile", headers={**headers(), "If-Match": '"1"'}, json={"nickname": "Next"})
    assert patched.status_code == 200 and patched.headers["etag"] == '"2"'
    assert client.patch("/api/v1/me/profile", headers={**headers(), "If-Match": '"1"'}, json={"nickname": "Stale"}).status_code == 412


def test_two_actors_private_resource_non_disclosure(client: httpx.Client) -> None:
    first = client.put("/api/v1/me/profile", headers=headers(), json={"nickname": "Synthetic"}).json()
    second = client.put("/api/v1/me/profile", headers=headers("actor-b"), json={"nickname": "Synthetic"}).json()
    assert first["user_id"] != second["user_id"]
    route = "/api/v1/profiles/" + first["user_id"]
    assert client.get(route, headers=headers()).status_code == 200
    assert client.get(route, headers=headers("actor-b")).status_code == 404
    assert client.patch(route, headers={**headers("actor-b"), "If-Match": '"1"'}, json={"nickname": "Attack"}).status_code == 404
    assert client.get("/api/v1/profiles/" + str(uuid4()), headers=headers("actor-b")).status_code == 404
    assert client.get(route, headers=headers()).json() == first


@pytest.mark.parametrize("field", ["user_id", "id", "issuer", "subject", "role", "state", "email", "version"])
def test_mass_assignment_protected_fields(client: httpx.Client, field: str) -> None:
    client.put("/api/v1/me/profile", headers=headers(), json={"nickname": "Synthetic"})
    before = client.get("/api/v1/me/profile", headers=headers()).json()
    body = {"nickname": "Synthetic", field: "synthetic-sensitive-value"}
    assert client.put("/api/v1/me/profile", headers=headers(), json=body).status_code == 422
    client.put("/api/v1/me/profile", headers=headers(), json={"nickname": "Synthetic"})
    assert client.patch("/api/v1/me/profile", headers={**headers(), "If-Match": '"1"'}, json=body).status_code == 422
    assert client.get("/api/v1/me/profile", headers=headers()).json() == before


@pytest.mark.parametrize("body", [{"nickname": " "}, {"nickname": "a" * 81}, {"nickname": "x\ny"}, {"nickname": 123}, {}])
def test_invalid_profile(client: httpx.Client, body: dict[str, object]) -> None:
    assert client.put("/api/v1/me/profile", headers=headers(), json=body).status_code == 422


def test_provider_failure_and_log_redaction(client: httpx.Client, capsys: pytest.CaptureFixture[str]) -> None:
    response = client.get("/api/v1/session?synthetic-query", headers=headers("provider-unavailable"))
    assert response.status_code == 503
    captured = capsys.readouterr()
    output = response.text + captured.out + captured.err
    for sensitive in ("provider-unavailable", "synthetic-secret-in-exception", "synthetic-query"):
        assert sensitive not in output


def test_local_limits_and_no_fake_in_local() -> None:
    pair = (FakeVerifier(), MemoryRepository())
    with pytest.raises(ValueError, match="test environment"):
        create_app(settings().model_copy(update={"environment": "local"}), Probe(True), identity_test=pair)
    for limits in (LocalLimits(requests=1), LocalLimits(writes=1)):
        with TestClient(create_app(settings(), Probe(True), identity_test=pair, test_limits=limits)) as transport:
            client = cast(httpx.Client, transport)
            assert client.put("/api/v1/me/profile", headers=headers(), json={"nickname": "Synthetic"}).status_code in {200, 201}
            response = client.put("/api/v1/me/profile", headers=headers(), json={"nickname": "Synthetic"})
            assert response.status_code == 429 and response.headers["retry-after"] == "60"


def test_unconfigured_provider_fails_closed() -> None:
    with TestClient(create_app(settings(), Probe(True))) as transport:
        assert cast(httpx.Client, transport).get("/api/v1/session", headers=headers()).status_code == 503


def test_oversized_body_refused_before_parsing(client: httpx.Client) -> None:
    response = client.put("/api/v1/me/profile", headers={**headers(), "Content-Type": "application/json"},
                          content=b"x" * 8193)
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    assert len(response.headers["x-correlation-id"]) == 32


def test_chunked_body_budget_does_not_trust_content_length() -> None:
    output: list[Message] = []
    messages = iter([{"type": "http.request", "body": b"x" * 6000, "more_body": True},
                     {"type": "http.request", "body": b"y" * 6000, "more_body": True}])

    async def receive() -> Message:
        return next(messages)

    async def send(message: Message) -> None:
        output.append(message)

    async def parser(_scope: Scope, _receive: Receive, _send: Send) -> None:
        raise AssertionError("Oversized body must not reach JSON parser")

    scope: Scope = {"type": "http", "method": "PATCH", "path": "/api/v1/me/profile",
                    "state": {"correlation_id": "0" * 32}}
    asyncio.run(IdentityBodyLimit(parser)(scope, receive, send))
    assert output[0]["type"] == "http.response.start" and output[0]["status"] == 413
