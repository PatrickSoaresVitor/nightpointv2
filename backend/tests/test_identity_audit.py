import asyncio
from dataclasses import fields
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from pathlib import Path
from typing import Any, Protocol, cast
from uuid import uuid4
from fastapi.testclient import TestClient
import httpx
import jsonschema
import pytest
from starlette.types import Message, Receive, Scope, Send

from app.bootstrap import create_app
from app.modules.identity import api
from app.modules.identity.body_limit import IdentityBodyLimit
from app.modules.identity.domain import ProfileValues, ProfileChanges
from app.modules.identity.domain import ExternalIdentity
from app.modules.identity.presentation import LocalLimits, ProfileInput, ProfilePatch
from tests.identity_fakes import FakeVerifier, MemoryRepository
from tests.test_foundation import settings, Probe
from tests.test_identity_http import headers
from tools.architecture import import_graph, verify, verify_ownership


def test_lookup_and_rejected_requests_never_enroll() -> None:
    repo = MemoryRepository()
    app = create_app(settings(), Probe(True), identity_test=(FakeVerifier(), repo))
    with TestClient(app) as transport:
        client = cast(httpx.Client, transport)
        for path in ("/api/v1/session", "/api/v1/me/profile", "/api/v1/profiles/" + str(uuid4())):
            assert client.get(path, headers=headers()).status_code == 409
        assert client.patch("/api/v1/me/profile", headers={**headers(), "If-Match": '"1"'}, json={"nickname": "x"}).status_code == 409
        assert client.put("/api/v1/me/profile", headers=headers(), json={"nickname": "x", "role": "admin"}).status_code == 422
        assert not repo.identities and not repo.profiles
        assert client.put("/api/v1/me/profile", headers=headers(), json={"nickname": "x"}).status_code == 201
        assert len(repo.identities) == len(repo.profiles) == 1


@pytest.mark.parametrize("suffix", ["/me/profile", "/profiles/{id}"])
def test_patch_preconditions_do_not_change_state(suffix: str) -> None:
    repo = MemoryRepository()
    with TestClient(create_app(settings(), Probe(True), identity_test=(FakeVerifier(), repo))) as transport:
        client = cast(httpx.Client, transport)
        created = client.put("/api/v1/me/profile", headers=headers(), json={"nickname": "Original", "avatar_seed": "seed"})
        path = "/api/v1" + suffix.replace("{id}", created.json()["user_id"])
        for condition, status in ((None,428), ('W/"1"',422), ('"0"',422), ('"2"',412)):
            response = client.patch(path, headers={**headers(), **({"If-Match":condition} if condition else {})}, json={"nickname":"Changed"})
            assert response.status_code == status and "etag" not in response.headers
            current = client.get(path, headers=headers())
            assert current.json() == created.json() and current.headers["etag"] == created.headers["etag"]
        for body in ({}, {"nickname":None}, {"user_id":str(uuid4())}):
            assert client.patch(path, headers={**headers(),"If-Match":'"1"'}, json=body).status_code == 422
        assert client.get(path, headers=headers()).json() == created.json()


def test_public_actor_contract_and_cross_module_fixtures(tmp_path: Path) -> None:
    assert set(api.__all__) == {"VerifiedActor", "ActorProvider"}
    assert [field.name for field in fields(api.VerifiedActor)] == ["user_id"]
    root = tmp_path / "app"
    identity = root / "modules/identity"
    consumer = root / "modules/consumer"
    identity.mkdir(parents=True)
    consumer.mkdir()
    (identity / "api.py").write_text(Path("app/modules/identity/api.py").read_text(encoding="utf-8"))
    (consumer / "application.py").write_text("from app.modules.identity.api import VerifiedActor\ndef author(actor: VerifiedActor): return actor.user_id")
    verify(import_graph(root))
    for source in ("from app.modules.identity.infrastructure import Repository",
                   "from app.modules.identity.private.api import Actor"):
        (consumer / "application.py").write_text(source)
        with pytest.raises(AssertionError):
            verify(import_graph(root))
    (consumer / "application.py").write_text("from app.modules.identity.api import VerifiedActor")
    (identity / "api.py").write_text("from .domain import PrivateProfile as VerifiedActor")
    (identity / "domain.py").write_text("class PrivateProfile: pass")
    with pytest.raises(AssertionError):
        verify(import_graph(root))
    (consumer / "infrastructure.py").write_text('SQL = \'INSERT INTO "accounts"."users"(id) VALUES(:id)\'')
    with pytest.raises(AssertionError):
        verify_ownership(root, {"identity":{"accounts"}, "consumer":{"consumer"}})
    (consumer / "infrastructure.py").write_text('SQL = "INSERT INTO consumer.owned(id) VALUES(:id)"')
    verify_ownership(root, {"identity":{"accounts"}, "consumer":{"consumer"}})
    # No consumer module is added to the application repository.


@pytest.mark.parametrize("value,valid", [("Night São 🚗",True), ("\u00a0",False), ("\u2003",False),
    ("a\u0085b",False), ("a\x00b",False), ("a\x7fb",False), ("a\u009fb",False),
    ("e\u0301",True), (" a ",True), ("a\u2028b",True), ("\u3000",False)])
def test_canonical_text_dto_domain_and_patch(value: str, valid: bool) -> None:
    if valid:
        assert ProfileInput(nickname=value).values() == ProfileValues(value)
        assert ProfilePatch(nickname=value).changes() == ProfileChanges({"nickname":value})
    else:
        for constructor in (ProfileInput, ProfilePatch, ProfileValues):
            with pytest.raises(ValueError):
                constructor(nickname=value)
    repository = MemoryRepository()
    with TestClient(create_app(settings(),Probe(True),identity_test=(FakeVerifier(),repository))) as transport:
        response = cast(httpx.Client,transport).put("/api/v1/me/profile",headers=headers(),json={"nickname":value})
        assert response.status_code == (201 if valid else 422)
        if not valid:
            assert not repository.identities and not repository.profiles


class DocumentValidator(Protocol):
    def validate(self, instance: object) -> None: ...


def test_independent_consumer_contract() -> None:
    schema = create_app(settings(), Probe(True)).openapi()
    for path in ("/api/v1/me/profile", "/api/v1/profiles/{user_id}"):
        operation = schema["paths"][path]["patch"]
        header = next(p for p in operation["parameters"] if p["name"] == "if-match")
        assert header["required"] is True and header["schema"]["type"] == "string"
        assert header["schema"]["pattern"] == '^"[1-9][0-9]{0,9}"$'
        assert {"412","428","200"}.issubset(operation["responses"])
        assert "ETag" in operation["responses"]["200"]["headers"]
    for path, operations in schema["paths"].items():
        if "health" in path:
            continue
        for operation in operations.values():
            for response in operation["responses"].values():
                assert "X-Correlation-ID" in response["headers"]
            if operation["operationId"] in {"myProfile","privateProfile","identitySession"}:
                assert not {"412","428","413"}.intersection(operation["responses"])
    patch: dict[str, Any] = schema["components"]["schemas"]["ProfilePatch"]
    for body in ({},{"nickname":None},{"role":"admin"}):
        with pytest.raises(jsonschema.ValidationError):
            cast(DocumentValidator, jsonschema.Draft202012Validator(patch)).validate(body)
    for body in ({"nickname":"Synthetic"},{"avatar_seed":None}):
        cast(DocumentValidator, jsonschema.Draft202012Validator(patch)).validate(body)


def test_slow_body_timeout_and_ingress_quota_before_receive() -> None:
    async def scenario() -> None:
        output: list[Message] = []
        reads = 0
        async def receive() -> Message:
            nonlocal reads
            reads += 1
            await asyncio.sleep(0.05)
            return {"type":"http.request","body":b"x","more_body":True}
        async def send(message: Message) -> None:
            output.append(message)
        async def parser(_scope: Scope, _receive: Receive, _send: Send) -> None:
            raise AssertionError("Must not parse rejected requests")
        scope: Scope = {"type":"http","method":"PUT","path":"/api/v1/me/profile","state":{"correlation_id":"0"*32}}
        await IdentityBodyLimit(parser, timeout=0.01)(scope, receive, send)
        assert output[0]["status"] == 408
        assert reads == 1
        output.clear()
        reads = 0
        await IdentityBodyLimit(parser, limits=LocalLimits(requests=0))(scope, receive, send)
        assert output[0]["status"] == 429 and reads == 0
    asyncio.run(scenario())


def test_auth_saturation_is_bounded_and_health_survives() -> None:
    entered, release = Event(), Event()
    lock = Lock()
    active = 0
    class SlowVerifier:
        def verify(self, token: str) -> ExternalIdentity:
            nonlocal active
            with lock:
                active += 1
                if active == 4:
                    entered.set()
            assert release.wait(5)
            return FakeVerifier().verify(token)
    limits = LocalLimits()
    app = create_app(settings(),Probe(True),identity_test=(SlowVerifier(),MemoryRepository()),test_limits=limits)
    with TestClient(app) as transport:
        client = cast(httpx.Client,transport)
        with ThreadPoolExecutor(max_workers=4) as pool:
            pending = [pool.submit(client.get,"/api/v1/session",headers=headers()) for _ in range(4)]
            try:
                assert entered.wait(5)
                response = client.get("/api/v1/session",headers=headers())
                assert response.status_code == 503 and response.headers["retry-after"] == "1"
                assert client.get("/api/v1/health/live").status_code == 200
            finally:
                release.set()
            assert all(result.result(timeout=5).status_code == 409 for result in pending)
    assert limits.auth_calls == 4 and limits.auth_saturation == 1 and limits.auth_seconds > 0
