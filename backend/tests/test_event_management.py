from concurrent.futures import ThreadPoolExecutor
import json
import time
from typing import Any, cast
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.bootstrap import create_app
from app.modules.events.domain import StaleEvent
from app.modules.events.infrastructure import PostgresEvents
from app.modules.events.presentation import CreateEvent
from app.modules.events.realtime import StreamSettings
from app.modules.identity.domain import ExternalIdentity
from app.modules.identity.infrastructure import PostgresIdentityRepository
from app.platform.database import Database
from app.platform.realtime import EventBus
from tests.identity_fakes import FakeVerifier
from tests.live_api import serve
from tests.test_database import engines as engines
from tests.test_discovery import search_body
from tests.test_events import event_store as event_store, event_body
from tests.test_identity_http import headers
from tests.test_realtime import next_kind, read_frame

@pytest.mark.integration
def test_private_event_owner_management_replay_and_no_physical_removal(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    migrator,_,identities=event_store
    with TestClient(create_app(identity_test=(FakeVerifier(),identities))) as transport:
        client=cast(httpx.Client,transport)
        key=str(uuid4())
        request_headers={**headers(),"Idempotency-Key":key}
        values=event_body(visibility="owner_only")
        created=client.post('/api/v1/events',headers=request_headers,json=values)
        assert created.status_code==201
        path=created.headers['location']
        assert created.json()['visibility']=='owner_only'
        assert client.get(path,headers=headers()).status_code==200
        assert client.get(path,headers=headers('actor-b')).status_code==404
        assert client.get(path+'/updates',headers=headers('actor-b')).status_code==404
        assert client.post('/api/v1/discovery/nearby',headers=headers(),json=search_body()).json()['items']==[]
        assert client.put(path,headers={**headers('actor-b'),'If-Match':'"1"'},json=values).status_code==404
        assert client.put(path,headers=headers(),json=values).status_code==428
        updated=client.put(path,headers={**headers(),'If-Match':'"1"'},json={**values,'title':'Revised synthetic event'})
        assert updated.status_code==200 and updated.headers['etag']=='"2"'
        assert client.put(path,headers={**headers(),'If-Match':'"1"'},json=values).status_code==412
        assert client.get('/api/v1/me/events',headers=headers('actor-b')).json()['items']==[]
        assert client.get('/api/v1/me/events',headers=headers()).json()['items'][0]['version']==2
        cancelled=client.post(path+'/cancel',headers={**headers(),'If-Match':'"2"'})
        assert cancelled.status_code==200 and cancelled.json()['state']=='cancelled'
        assert client.get(path,headers=headers('actor-b')).status_code==404
        replay=client.post('/api/v1/events',headers=request_headers,json=values)
        assert replay.status_code==201 and replay.json()['id']==created.json()['id']
        assert replay.json()['state']=='cancelled' and replay.json()['version']==3
        assert client.put(path,headers={**headers(),'If-Match':'"3"'},json=values).status_code==409
    with migrator.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM events.events'))==1
        assert connection.scalar(text('SELECT count(*) FROM events.creation_requests'))==1


@pytest.mark.parametrize('email,allowed',[(False,False),(True,False),(False,True)])
@pytest.mark.integration
def test_publication_fails_closed_without_both_trusted_evidences(event_store: tuple[Engine,Database,PostgresIdentityRepository],email: bool,allowed: bool) -> None:
    migrator,_,identities=event_store
    class Unqualified:
        def verify(self,token: str) -> ExternalIdentity:
            identity=FakeVerifier().verify(token)
            return ExternalIdentity(identity.issuer,identity.subject,email_verified=email,publication_authorized=allowed)
    with TestClient(create_app(identity_test=(Unqualified(),identities))) as transport:
        client=cast(httpx.Client,transport)
        assert client.get('/api/v1/me/profile',headers=headers()).status_code==200
        response=client.post('/api/v1/events',headers={**headers(),'Idempotency-Key':str(uuid4())},json=event_body())
        assert response.status_code==403
    with migrator.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM events.events'))==0


@pytest.mark.integration
def test_concurrent_updates_have_one_winner(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    _,runtime,identities=event_store
    repository=PostgresEvents(runtime)
    actor=identities.resolve(ExternalIdentity('synthetic-issuer','actor-a'));assert actor is not None
    values=CreateEvent.model_validate(event_body()).value()
    created,_=repository.create(actor,uuid4(),values)
    def update(_: int) -> str:
        try:repository.update(actor,created.id,values,1)
        except StaleEvent:return 'stale'
        return 'updated'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(update,range(2)))==['stale','updated']
    observed=repository.detail(created.id,actor)
    assert observed is not None and observed.version==2


@pytest.mark.integration
def test_mutation_rechecks_visibility_before_cursor_ranking(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    _,_,identities=event_store
    with TestClient(create_app(identity_test=(FakeVerifier(),identities))) as transport:
        client=cast(httpx.Client,transport)
        entries: dict[str,dict[str,Any]]={}
        for index in range(3):
            values=event_body(title=f'Synthetic {index}')
            response=client.post('/api/v1/events',headers={**headers(),'Idempotency-Key':str(uuid4())},json=values)
            assert response.status_code==201
            entries[response.json()['id']]=values
        first=client.post('/api/v1/discovery/nearby',headers=headers(),json=search_body(limit=1)).json()
        changed=sorted(entries)[1]
        response=client.put('/api/v1/events/'+changed,headers={**headers(),'If-Match':'"1"'},
            json={**entries[changed],'visibility':'owner_only'})
        assert response.status_code==200
        second=client.post('/api/v1/discovery/nearby',headers=headers(),json=search_body(limit=1,cursor=first['next_cursor'])).json()
        assert [item['id'] for item in second['items']]==[sorted(entries)[2]]
        assert second['next_cursor'] is None
        assert client.get('/api/v1/events/'+changed,headers=headers('actor-b')).status_code==404


def test_default_creation_fingerprint_remains_compatible_with_05a() -> None:
    expected={'title':'Synthetic meetup','category_code':'jdm','starts_at':'2030-02-01T12:00:00+00:00',
        'timezone':'UTC','location_label':'Synthetic point','longitude':0.0,'latitude':0.0,'description':None}
    assert CreateEvent.model_validate(event_body()).value().canonical()==expected


@pytest.mark.integration
def test_private_stream_delivers_only_owner_committed_edits_and_cancellation(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    _,_,identities=event_store
    app=create_app(identity_test=(FakeVerifier(),identities),test_streams=StreamSettings(.05,.1,10))
    bus=cast(EventBus,app.state.event_bus)
    with serve(app) as url,httpx.Client(base_url=url,trust_env=False,timeout=5) as client:
        values=event_body(visibility='owner_only')
        created=client.post('/api/v1/events',headers={**headers(),'Idempotency-Key':str(uuid4())},json=values)
        assert created.status_code==201
        path=created.headers['location']
        assert client.get(path+'/updates',headers=headers('actor-b')).status_code==404
        with client.stream('GET',path+'/updates',headers=headers()) as stream:
            assert stream.status_code==200
            lines=iter(stream.iter_lines())
            assert json.loads(read_frame(lines)['data'])=={'version':1}
            edited=client.put(path,headers={**headers(),'If-Match':'"1"'},json={**values,'title':'Private revised'})
            assert edited.status_code==200
            assert json.loads(next_kind(lines,'changed')['data'])=={'version':2}
            assert client.get(path,headers=headers()).json()['title']=='Private revised'
            cancelled=client.post(path+'/cancel',headers={**headers(),'If-Match':'"2"'})
            assert cancelled.status_code==200
            assert json.loads(next_kind(lines,'changed')['data'])=={'version':3}
            assert client.get(path,headers=headers()).json()['state']=='cancelled'
        deadline=time.monotonic()+2
        while bus.active and time.monotonic()<deadline:time.sleep(.01)
        assert bus.active==0
