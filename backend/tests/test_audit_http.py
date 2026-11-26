from http import HTTPStatus
from io import StringIO
import logging
from typing import cast

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from app.bootstrap import create_app
from app.platform.logging import JsonFormatter
from tests.test_foundation import Probe, settings


@pytest.mark.parametrize("status,headers", [
    (401, {"www-authenticate": 'Bearer realm="nightpoint"'}),
    (405, {"Allow": "GET"}), (429, {"Retry-After": "10"}),
    (416, {"Content-Range": "bytes */100"}),
])
def test_semantic_headers(status: int, headers: dict[str, str]) -> None:
    application = create_app(settings(), Probe(True))

    @application.get("/_test/error")
    def failure() -> None:
        raise HTTPException(status, detail="synthetic-sensitive", headers={**headers, "X-Private-Token": "synthetic-sensitive"})

    with TestClient(application) as transport:
        client = cast(httpx.Client, transport)
        response = client.get("/_test/error")
        assert response.status_code == status
        for key, value in headers.items():
            assert response.headers[key] == value
        assert response.json()["title"] == HTTPStatus(status).phrase
        assert response.headers["content-type"] == "application/problem+json"
        assert "synthetic-sensitive" not in response.text
        assert "X-Private-Token" not in response.headers
        assert response.json()["correlation_id"] == response.headers["X-Correlation-ID"]


def test_ingress_body_query_exception_and_message_redaction() -> None:
    sentinel = "synthetic-token-credential-1234"
    application = create_app(settings(), Probe(True))
    captured = StringIO()
    handler = logging.StreamHandler(captured)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("nightpoint")
    logger.addHandler(handler)

    @application.post("/_test/failure")
    def failure() -> None:
        raise RuntimeError(sentinel)

    try:
        with TestClient(application, raise_server_exceptions=False) as transport:
            client = cast(httpx.Client, transport)
            response = client.post("/_test/failure?token=" + sentinel, json={"password": sentinel},
                headers={"Authorization": "Bearer " + sentinel, "X-Correlation-ID": sentinel})
            assert response.status_code == 500
            assert sentinel not in response.text and sentinel not in str(response.headers)
        logger.error(sentinel, exc_info=RuntimeError(sentinel), extra={"correlation_id": sentinel, "status": sentinel})
        assert sentinel not in captured.getvalue()
        assert "redacted_event" in captured.getvalue()
    finally:
        logger.removeHandler(handler)


def test_lifespan_releases_pool_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import bootstrap
    closed: list[bool] = []

    class InstrumentedDatabase:
        def __init__(self, _: object) -> None:
            pass

        def ready(self) -> bool:
            return True

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(bootstrap, "Database", InstrumentedDatabase)
    application = create_app(settings())
    with pytest.raises(RuntimeError, match="synthetic"):
        with TestClient(application):
            raise RuntimeError("synthetic")
    assert closed == [True]
