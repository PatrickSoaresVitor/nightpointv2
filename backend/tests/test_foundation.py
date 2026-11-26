from pathlib import Path
import json
import logging
from typing import cast
import httpx

from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
import pytest

from app.bootstrap import create_app
from app.platform.config import Settings, load_settings
from app.platform.logging import JsonFormatter
from app.presentation.contracts import PageQuery


class Probe:
    def __init__(self, available: bool) -> None:
        self.available = available

    def ready(self) -> bool:
        return self.available


def settings() -> Settings:
    return Settings(environment="test", db_password=SecretStr("synthetic-test-value-never-used"))


def test_live_and_failed_readiness() -> None:
    with TestClient(create_app(settings(), Probe(False))) as transport:
        client = cast(httpx.Client, transport)
        assert client.get("/api/v1/health/live").json() == {"status": "ok"}
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["correlation_id"] == response.headers["X-Correlation-ID"]


def test_correlation_errors_and_redaction() -> None:
    with TestClient(create_app(settings(), Probe(True))) as transport:
        client = cast(httpx.Client, transport)
        response = client.get("/api/v1/health/live", headers={"X-Correlation-ID": "sample-123"})
        assert response.headers["X-Correlation-ID"] != "sample-123"
        assert len(response.headers["X-Correlation-ID"]) == 32
        assert client.get("/api/v1/health/ready").status_code == 200
        assert client.get("/api/v1/health/live", headers={"X-Correlation-ID": "a" * 65}).status_code == 400
        response = client.get("/private-synthetic?token=synthetic-sensitive")
        assert response.status_code == 404
        assert "synthetic-sensitive" not in response.text
        assert "private-synthetic" not in response.text
        not_allowed = client.post("/api/v1/health/live")
        assert not_allowed.status_code == 405 and "GET" in not_allowed.headers["Allow"]


def test_configuration_fail_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("NP_DB_PASSWORD_FILE", raising=False)
    with pytest.raises(ValueError, match="required"):
        load_settings()
    path = tmp_path / "test-secret"
    path.write_text("synthetic-only-password-length-32")
    monkeypatch.setenv("NP_DB_PASSWORD_FILE", str(path))
    monkeypatch.setenv("NP_ENV", "production")
    with pytest.raises(ValidationError):
        load_settings()
    monkeypatch.setenv("NP_ENV", "test")
    configuration = load_settings()
    assert "synthetic-only-password" not in repr(configuration)
    assert "synthetic-only-password" not in str(configuration.database_url())
    with pytest.raises(ValueError, match="runtime"):
        create_app(configuration.model_copy(update={"db_user": "np_migrator"}), Probe(True))


@pytest.mark.parametrize("data", [{"limit": 0}, {"limit": 101}, {"cursor": "bad cursor"}, {"other": 1}])
def test_pagination_validation(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PageQuery.model_validate(data)


def test_structured_logs_allowlist() -> None:
    record = logging.LogRecord("nightpoint", logging.INFO, "", 0, "http_request", (), None)
    record.__dict__.update(correlation_id="a" * 32, status=200, password="must-not-log")
    output = JsonFormatter().format(record)
    assert "must-not-log" not in output
    assert json.loads(output)["correlation_id"] == "a" * 32
