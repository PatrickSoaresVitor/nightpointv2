import logging
from typing import cast

from fastapi.testclient import TestClient
import httpx
import pytest

from app.bootstrap import create_app
from app.modules.identity.domain import InvalidToken
from tests.test_foundation import settings, Probe
from tools.local_demo import SyntheticSessions, SessionCapacity, create_demo_app, local_origin


def test_synthetic_identity_expires_revokes_and_has_bounded_capacity() -> None:
    clock=[1000.0]
    sessions=SyntheticSessions(ttl=2,capacity=2,clock=lambda:clock[0])
    first=sessions.issue('participant-a');second=sessions.issue('participant-b')
    assert first!=second and len(first)>=40
    identity=sessions.verify(first)
    assert identity.subject=='participant-a' and identity.email_verified and identity.publication_authorized
    with pytest.raises(SessionCapacity):sessions.issue('participant-a')
    sessions.revoke(first)
    with pytest.raises(InvalidToken):sessions.verify(first)
    clock[0]=1003
    with pytest.raises(InvalidToken):sessions.verify(second)
    assert sessions.verify(sessions.issue('participant-a')).subject=='participant-a'
    sessions.close()


@pytest.mark.parametrize('origin',['https://127.0.0.1:5173','http://example.com:5173',
    'http://a:b@localhost:5173','http://localhost:5173/path','http://localhost:5173/?token=x','http://localhost'])
def test_demo_cors_rejects_nonlocal_or_credential_origins(origin: str) -> None:
    with pytest.raises(ValueError):local_origin(origin)


def test_normal_api_never_exposes_demo_and_non_test_cannot_select_fake_verifier() -> None:
    configuration=settings()
    assert not any('/demo/' in path for path in create_app(configuration,Probe(True)).openapi()['paths'])
    local=configuration.model_copy(update={'environment':'local'})
    with pytest.raises(ValueError):create_demo_app(local,Probe(True))
    with pytest.raises(ValueError):create_app(local,Probe(True),test_verifier=SyntheticSessions())


def test_explicit_demo_session_cors_logout_and_log_redaction(caplog: pytest.LogCaptureFixture) -> None:
    application=create_demo_app(settings(),Probe(True))
    with caplog.at_level(logging.INFO,logger='nightpoint'),TestClient(application) as transport:
        client=cast(httpx.Client,transport)
        assert client.post('/api/v1/demo/session',json={'persona':'participant-a','publication_authorized':True}).status_code==422
        issued=client.post('/api/v1/demo/session',json={'persona':'participant-a'})
        assert issued.status_code==200 and issued.headers['cache-control']=='no-store'
        token=issued.json()['access_token']
        assert issued.json()['mode']=='synthetic'
        accepted=client.options('/api/v1/demo/session',headers={'Origin':'http://127.0.0.1:5173',
            'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'content-type'})
        assert accepted.status_code==200 and accepted.headers['access-control-allow-origin']=='http://127.0.0.1:5173'
        denied=client.options('/api/v1/demo/session',headers={'Origin':'http://outside.invalid',
            'Access-Control-Request-Method':'POST'})
        assert denied.status_code==400 and 'access-control-allow-origin' not in denied.headers
        assert client.post('/api/v1/demo/logout',headers=[('Authorization','Bearer '+token),
            ('Authorization','Bearer '+token)]).status_code==401
        assert client.post('/api/v1/demo/logout',headers={'Authorization':'Bearer '+token}).status_code==204
        assert client.post('/api/v1/demo/logout',headers={'Authorization':'Bearer '+token}).status_code==401
        assert token not in caplog.text
