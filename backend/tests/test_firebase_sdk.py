"""Real SDK signature/claims verification, synthetic ephemeral keys, blocked transport.

Only certificate transport and account-status lookup are substituted; JWT verification
is performed by the unmodified Firebase/Google SDK. No emulator or remote project.
"""
from collections.abc import Iterator
import io
import json
import logging
from types import SimpleNamespace
import time
from typing import Any
from typing import cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from google.auth.credentials import AnonymousCredentials
import jwt
import pytest
import requests
from firebase_admin import auth, exceptions
import httpx
from fastapi.testclient import TestClient

from app.modules.identity.domain import ExternalIdentity, InvalidToken, ProviderUnavailable
from app.modules.identity.firebase import FirebaseVerifier, FirebaseConfiguration
from app.bootstrap import create_app
from app.platform.logging import JsonFormatter
from tests.identity_fakes import MemoryRepository
from tests.test_foundation import Probe, settings


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[FirebaseVerifier, rsa.RSAPrivateKey]]:
    monkeypatch.delenv("FIREBASE_AUTH_EMULATOR_HOST", raising=False)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def transport(_self: object, method: str, url: str, **_kwargs: Any) -> requests.Response:
        assert method.upper() == "GET"
        assert url == "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
        response = requests.Response()
        response.status_code = 200
        response.raw = io.BytesIO(json.dumps({"synthetic-key": public}).encode())
        response.headers["Content-Type"] = "application/json"
        return response

    def account(_self: object, _uid: str) -> SimpleNamespace:
        return SimpleNamespace(disabled=False, tokens_valid_after_timestamp=0)

    monkeypatch.setattr(requests.Session, "request", transport)
    monkeypatch.setattr("firebase_admin._auth_client.Client.get_user", account)
    verifier = FirebaseVerifier(FirebaseConfiguration("nightpoint-synthetic", "test", "explicit-isolated-composition"), AnonymousCredentials())
    try:
        yield verifier, key
    finally:
        verifier.close()


def signed(key: rsa.RSAPrivateKey, changes: dict[str, Any] | None = None) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {"iss": "https://securetoken.google.com/nightpoint-synthetic",
        "aud": "nightpoint-synthetic", "sub": "synthetic-subject", "iat": now - 3600,
        "exp": now + 300, "auth_time": now - 3600}
    payload.update(changes or {})
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": "synthetic-key"})


def test_official_sdk_accepts_valid_signature_claims(sdk: tuple[FirebaseVerifier, rsa.RSAPrivateKey]) -> None:
    verifier, key = sdk
    assert verifier.verify(signed(key)) == ExternalIdentity(
        "https://securetoken.google.com/nightpoint-synthetic", "synthetic-subject")


@pytest.mark.parametrize("changes", [{"exp": 1}, {"aud": "another-project"},
    {"iss": "https://securetoken.google.com/another-project"}, {"sub": ""}])
def test_official_sdk_refuses_claims(sdk: tuple[FirebaseVerifier, rsa.RSAPrivateKey], changes: dict[str, Any]) -> None:
    verifier, key = sdk
    with pytest.raises(InvalidToken):
        verifier.verify(signed(key, changes))


def test_official_sdk_refuses_wrong_signature_and_malformed(sdk: tuple[FirebaseVerifier, rsa.RSAPrivateKey]) -> None:
    verifier, _ = sdk
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for token in (signed(other_key), "not.a.jwt"):
        with pytest.raises(InvalidToken):
            verifier.verify(token)


@pytest.mark.parametrize("disabled,revoked", [(True, False), (False, True)])
def test_official_revocation_and_disabled_status(sdk: tuple[FirebaseVerifier, rsa.RSAPrivateKey],
    monkeypatch: pytest.MonkeyPatch, disabled: bool, revoked: bool) -> None:
    def account(_self: object, _uid: str) -> SimpleNamespace:
        return SimpleNamespace(disabled=disabled, tokens_valid_after_timestamp=int(time.time()) * 1000 if revoked else 0)
    monkeypatch.setattr("firebase_admin._auth_client.Client.get_user", account)
    with pytest.raises(InvalidToken):
        sdk[0].verify(signed(sdk[1]))


def test_certificate_provider_unavailable_and_emulator_refused(sdk: tuple[FirebaseVerifier, rsa.RSAPrivateKey],
    monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(*_args: Any, **_kwargs: Any) -> requests.Response:
        raise requests.exceptions.ConnectionError("synthetic-private-error")
    monkeypatch.setattr(requests.Session, "request", offline)
    with pytest.raises(ProviderUnavailable):
        sdk[0].verify(signed(sdk[1]))
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST", "127.0.0.1:9099")
    with pytest.raises(ProviderUnavailable):
        sdk[0].verify(signed(sdk[1]))
    with pytest.raises(ValueError):
        FirebaseVerifier(sdk[0].configuration, AnonymousCredentials())


def test_real_sdk_http_errors_and_sanitized_logs(sdk: tuple[FirebaseVerifier, rsa.RSAPrivateKey]) -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("nightpoint")
    logger.addHandler(handler)
    verifier, key = sdk
    app = create_app(settings(), Probe(True), identity_test=(verifier, MemoryRepository()))
    try:
        with TestClient(app) as transport:
            client = cast(httpx.Client, transport)
            for changes in ({"exp": 1}, {"aud": "private-project-sentinel"}, {"iss": "private-issuer-sentinel"}):
                token = signed(key, changes)
                response = client.get("/api/v1/session", headers={"Authorization": "Bearer " + token})
                assert response.status_code == 401 and response.headers["www-authenticate"] == "Bearer"
                assert token not in response.text + stream.getvalue()
            assert "private-project-sentinel" not in stream.getvalue()
            assert "private-issuer-sentinel" not in stream.getvalue()
            assert "http_request" in stream.getvalue()
    finally:
        logger.removeHandler(handler)


@pytest.mark.parametrize("tenant", ["unapproved-tenant", ""])
def test_sdk_tenant_refused_before_status_lookup(sdk: tuple[FirebaseVerifier, rsa.RSAPrivateKey],
    monkeypatch: pytest.MonkeyPatch, tenant: str) -> None:
    def no_status(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Must not query account status in an unapproved namespace")
    monkeypatch.setattr("firebase_admin._auth_client.Client.get_user",no_status)
    with pytest.raises(InvalidToken):
        sdk[0].verify(signed(sdk[1],{"firebase":{"tenant":tenant}}))


@pytest.mark.parametrize("missing", [True,False])
def test_sdk_account_absent_or_status_unavailable(sdk: tuple[FirebaseVerifier, rsa.RSAPrivateKey],
    monkeypatch: pytest.MonkeyPatch, missing: bool) -> None:
    def account(*_args: Any, **_kwargs: Any) -> None:
        if missing:
            raise auth.UserNotFoundError("synthetic-account-absent")
        raise exceptions.UnavailableError("synthetic-provider-failure")
    monkeypatch.setattr("firebase_admin._auth_client.Client.get_user",account)
    with pytest.raises(InvalidToken if missing else ProviderUnavailable):
        sdk[0].verify(signed(sdk[1]))


def test_explicit_configuration_readiness_environment_and_timeout(sdk: tuple[FirebaseVerifier, rsa.RSAPrivateKey],
    monkeypatch: pytest.MonkeyPatch) -> None:
    verifier, _ = sdk
    assert verifier.ready()
    with pytest.raises(ValueError):
        FirebaseConfiguration("nightpoint-synthetic","test","explicit-isolated-composition",timeout_seconds=10)
    with pytest.raises(ValueError):
        FirebaseConfiguration("not/a/project","test","explicit-isolated-composition")
    with pytest.raises(ValueError,match="environments must match"):
        create_app(settings().model_copy(update={"environment":"local"}),Probe(True),firebase=verifier)
    application = create_app(settings(),Probe(True),firebase=verifier)
    monkeypatch.setenv("FIREBASE_AUTH_EMULATOR_HOST","127.0.0.1:9099")
    assert not verifier.ready()
    with TestClient(application) as transport:
        assert cast(httpx.Client,transport).get("/api/v1/health/ready").status_code == 503
