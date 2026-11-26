from copy import deepcopy
from pathlib import Path
from typing import Any, cast
import httpx

from fastapi import Body, HTTPException
from fastapi.testclient import TestClient
from openapi_spec_validator import validate
import pytest
import yaml

from app.bootstrap import create_app
from app.presentation.contracts import PageQuery
from tests.test_foundation import Probe, settings


def require_preserved_operations(old: dict[str, Any], new: dict[str, Any]) -> None:
    """Small operation-removal guard; exact snapshot catches all other drift."""
    for path, operations in old["paths"].items():
        assert path in new["paths"], f"Removed path: {path}"
        for method, operation in operations.items():
            assert method in new["paths"][path], f"Removed method: {method}"
            for status in operation["responses"]:
                assert status in new["paths"][path][method]["responses"], f"Removed status: {status}"


def test_openapi_valid_and_matches_versioned_snapshot() -> None:
    schema = create_app(settings(), Probe(True)).openapi()
    validate(schema)
    snapshot = Path("contracts/openapi.yaml")
    if not snapshot.exists():
        snapshot = Path("../contracts/openapi.yaml")
    expected = yaml.safe_load(snapshot.read_text(encoding="utf-8"))
    require_preserved_operations(expected, schema)
    assert schema == expected, "Contract drift requires explicit review and snapshot update"
    baseline = snapshot.with_name("foundation-openapi.yaml")
    original = yaml.safe_load(baseline.read_text(encoding="utf-8"))
    require_preserved_operations(original, schema)
    for path, operations in original["paths"].items():
        assert schema["paths"][path] == operations, "Operational contract changed"
    for name, definition in original["components"]["schemas"].items():
        assert schema["components"]["schemas"][name] == definition
    identity = yaml.safe_load(snapshot.with_name("identity-04-1-openapi.yaml").read_text(encoding="utf-8"))
    for path, operations in identity["paths"].items():
        assert schema["paths"][path] == operations, "Previous identity contract changed"
    for name, definition in identity["components"]["schemas"].items():
        assert schema["components"]["schemas"][name] == definition
    assert set(schema["paths"]) == {"/api/v1/health/live", "/api/v1/health/ready",
        "/api/v1/session", "/api/v1/me/profile", "/api/v1/profiles/{user_id}",
        "/api/v1/events", "/api/v1/events/{event_id}", "/api/v1/discovery/nearby", "/api/v1/events/{event_id}/updates",
        "/api/v1/me/events", "/api/v1/events/{event_id}/cancel",
        "/api/v1/me/vehicles", "/api/v1/me/vehicles/{identifier}", "/api/v1/me/vehicles/{identifier}/history",
        "/api/v1/events/{event_id}/community", "/api/v1/events/{event_id}/community/reactions/{kind}",
        "/api/v1/events/{event_id}/community/comments", "/api/v1/events/{event_id}/community/comments/{comment_id}",
        "/api/v1/events/{event_id}/community/comments/{comment_id}/visibility"}


def test_contract_guard_rejects_removed_operation() -> None:
    schema = create_app(settings(), Probe(True)).openapi()
    broken = deepcopy(schema)
    del broken["paths"]["/api/v1/health/ready"]
    with pytest.raises(AssertionError, match="Removed path"):
        require_preserved_operations(schema, broken)


def test_validation_http_and_unhandled_errors_do_not_leak() -> None:
    application = create_app(settings(), Probe(True))

    # Test-only routes exercise handlers; never present in deployed app/contract.
    @application.post("/_test/validation")
    def validate_input(value: PageQuery = Body()) -> PageQuery:
        return value

    @application.get("/_test/http")
    def http_failure() -> None:
        raise HTTPException(403, detail="synthetic-sensitive")

    @application.get("/_test/crash")
    def crash() -> None:
        raise RuntimeError("synthetic-sensitive")

    with TestClient(application, raise_server_exceptions=False) as transport:
        client = cast(httpx.Client, transport)
        for response, status in [
            (client.post("/_test/validation", json={"cursor": "synthetic-sensitive ", "limit": 0}), 422),
            (client.get("/_test/http"), 403),
            (client.get("/_test/crash"), 500),
        ]:
            assert response.status_code == status
            assert response.headers["content-type"] == "application/problem+json"
            assert "synthetic-sensitive" not in response.text
            assert response.json()["status"] == status
            assert response.json()["correlation_id"] == response.headers["X-Correlation-ID"]
