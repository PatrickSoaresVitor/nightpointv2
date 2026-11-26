from collections.abc import Iterator
from datetime import datetime, timezone, timedelta
import json
from queue import Empty
from typing import cast
from uuid import uuid4
import time
import httpx
import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from app.bootstrap import create_app
from app.modules.events.application import EventService
from app.modules.events.domain import EventInput
from app.modules.events.infrastructure import PostgresEvents
from app.modules.events.presentation import actor_provider
from app.modules.events.realtime import StreamSettings
from app.modules.identity.api import VerifiedActor
from app.modules.identity.domain import ExternalIdentity, InvalidToken
from app.modules.identity.infrastructure import PostgresIdentityRepository
from app.platform.database import Database
from app.platform.realtime import EventBus, ConnectionLimit, Change
from tests.identity_fakes import FakeVerifier
from tests.live_api import serve
from tests.test_database import engines as engines
from tests.test_events import event_store as event_store, event_body
from tests.test_identity_http import headers


def read_frame(lines: Iterator[str]) -> dict[str,str]:
    result: dict[str,str]={}
    for line in lines:
        if not line:
            if result:return result
            continue
        key,_,value=line.partition(":")
        result[key]=value.strip()
    raise AssertionError("Stream ended before the expected frame")


def next_kind(lines: Iterator[str],kind: str) -> dict[str,str]:
    for _ in range(100):
        item=read_frame(lines)
        if item.get("event")==kind:return item
    raise AssertionError("Expected stream event was not observed")


def test_bus_bounded_scope_deduplication_order_and_cleanup() -> None:
    bus=EventBus(total=3,per_actor=2)
    identifier,actor=uuid4(),uuid4()
    one=bus.subscribe(identifier,actor,1)
    two=bus.subscribe(identifier,actor,1)
    with pytest.raises(ConnectionLimit):bus.subscribe(identifier,actor,1)
    other=bus.subscribe(uuid4(),uuid4(),1)
    with pytest.raises(ConnectionLimit):bus.subscribe(identifier,uuid4(),1)
    bus.publish(identifier,2);bus.publish(identifier,2);bus.publish(identifier,1)
    assert one.messages.get_nowait().version==2
    with pytest.raises(Empty):one.messages.get_nowait()
    with pytest.raises(Empty):other.messages.get_nowait()
    assert two.messages.get_nowait().version==2
    for version in range(3,30):bus.publish(identifier,version)
    assert one.messages.qsize()<=8
    messages: list[Change]=[]
    while not one.messages.empty():messages.append(one.messages.get_nowait())
    assert any(message.kind=="resync" for message in messages)
    assert messages[-1].version==29
    bus.unsubscribe(one);bus.unsubscribe(one)
    assert bus.active==2
    bus.close();assert bus.active==0 and two.closed and other.closed


@pytest.mark.integration
def test_post_commit_creation_and_rollback_are_real(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    _,runtime,identities=event_store
    repository=PostgresEvents(runtime)
    seen: list[int]=[]
    class CommitProbe:
        def publish(self,identifier: object,version: int) -> None:
            from uuid import UUID
            assert isinstance(identifier,UUID)
            # Separate pool checkout must already see the committed row.
            assert repository.detail(identifier) is not None
            seen.append(version)
    service=EventService(repository,CommitProbe())
    actor=identities.resolve(ExternalIdentity("synthetic-issuer","actor-a"));assert actor is not None
    provider=actor_provider(VerifiedActor(actor))
    value=EventInput("Synthetic","jdm",datetime(2030,2,1,tzinfo=timezone.utc),"UTC","Synthetic",0,0)
    key=uuid4()
    created=service.create(provider,key,value)
    assert seen==[1] and service.create(provider,key,value).id==created.id and seen==[1]
    def interrupt(_conn: object,_cursor: object,statement: str,_parameters: object,_context: object,_many: bool) -> None:
        if statement.startswith("INSERT INTO events.creation_requests"):raise RuntimeError("Synthetic rollback")
    event.listen(runtime.engine,"before_cursor_execute",interrupt)
    try:
        with pytest.raises(RuntimeError):service.create(provider,uuid4(),value)
    finally:event.remove(runtime.engine,"before_cursor_execute",interrupt)
    assert seen==[1]


@pytest.mark.integration
def test_two_live_clients_commit_rollback_loss_and_rest_reconciliation(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    migrator,_,identities=event_store
    app=create_app(identity_test=(FakeVerifier(),identities),test_streams=StreamSettings(.05,.15,5))
    bus=cast(EventBus,app.state.event_bus)
    with serve(app) as url, httpx.Client(base_url=url,trust_env=False,timeout=5) as client:
        created=client.post("/api/v1/events",headers={**headers(),"Idempotency-Key":str(uuid4())},json=event_body())
        assert created.status_code==201
        identifier=created.json()["id"]
        resource="/api/v1/events/"+identifier
        with client.stream("GET",resource+"/updates",headers=headers()) as first,client.stream("GET",resource+"/updates",headers=headers("actor-b")) as second:
            assert first.status_code==second.status_code==200
            assert first.headers["content-type"].startswith("text/event-stream")
            lines1,lines2=iter(first.iter_lines()),iter(second.iter_lines())
            assert read_frame(lines1)["event"]==read_frame(lines2)["event"]=="resync"
            assert bus.active==2
            from uuid import UUID
            # Controlled integration mutation, not a public editing endpoint.
            with migrator.begin() as conn:
                conn.execute(text("UPDATE events.events SET title='Committed',version=2 WHERE id=:id"),{"id":identifier})
            before=time.monotonic();bus.publish(UUID(identifier),2)
            for lines in (lines1,lines2):
                changed=next_kind(lines,"changed")
                assert json.loads(changed["data"])=={"version":2}
            assert time.monotonic()-before<3
            assert client.get(resource,headers=headers("actor-b")).json()["title"]=="Committed"
            # Rollback does not publish and REST remains at v2.
            with pytest.raises(RuntimeError):
                with migrator.begin() as conn:
                    conn.execute(text("UPDATE events.events SET title='Rolled back',version=3 WHERE id=:id"),{"id":identifier})
                    raise RuntimeError("Synthetic rollback")
            assert client.get(resource,headers=headers()).json()["version"]==2
            assert json.loads(next_kind(lines1,"resync")["data"])["version"]==2
            # Commit with intentionally lost notification: periodic resync plus REST converges.
            with migrator.begin() as conn:
                conn.execute(text("UPDATE events.events SET title='Recovered',version=3 WHERE id=:id"),{"id":identifier})
            for lines in (lines1,lines2):
                for _ in range(100):
                    sync=next_kind(lines,"resync")
                    if json.loads(sync["data"])["version"]==3:break
                else:raise AssertionError("Silent notification loss did not reconcile")
            assert client.get(resource,headers=headers()).json()["title"]=="Recovered"
        deadline=time.monotonic()+2
        while bus.active and time.monotonic()<deadline:time.sleep(.02)
        assert bus.active==0
        with client.stream("GET",resource+"/updates",headers={**headers(),"Last-Event-ID":"1"}) as reopened:
            assert read_frame(iter(reopened.iter_lines()))["event"]=="resync"


@pytest.mark.integration
def test_sse_auth_scope_limit_expiration_revocation_and_cleanup(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    migrator,_,identities=event_store
    class LeaseVerifier:
        revoked=False
        def verify(self,token: str) -> ExternalIdentity:
            if self.revoked:raise InvalidToken()
            identity=FakeVerifier().verify(token)
            return ExternalIdentity(identity.issuer,identity.subject,datetime.now(timezone.utc)+timedelta(seconds=.8),
                                    email_verified=identity.email_verified,publication_authorized=identity.publication_authorized)
    verifier=LeaseVerifier()
    app=create_app(identity_test=(verifier,identities),test_streams=StreamSettings(.05,.1,1))
    bus=cast(EventBus,app.state.event_bus)
    with serve(app) as url,httpx.Client(base_url=url,trust_env=False,timeout=5) as client:
        created=client.post("/api/v1/events",headers={**headers(),"Idempotency-Key":str(uuid4())},json=event_body()).json()
        path="/api/v1/events/"+created["id"]+"/updates"
        assert client.get(path).status_code==401
        assert client.get("/api/v1/events/"+str(uuid4())+"/updates",headers=headers()).status_code==404
        assert client.get(path,headers={**headers(),"Last-Event-ID":"invalid"}).status_code==422
        with client.stream("GET",path,headers=headers()) as one,client.stream("GET",path,headers=headers()) as two:
            assert one.status_code==two.status_code==200
            assert client.get(path,headers=headers()).status_code==429
            lines=iter(one.iter_lines())
            assert next_kind(lines,"session-expired")["data"]=="{}"
        deadline=time.monotonic()+2
        while bus.active and time.monotonic()<deadline:time.sleep(.02)
        assert bus.active==0
        verifier.revoked=True
        assert client.get(path,headers=headers()).status_code==401
        verifier.revoked=False
        with migrator.begin() as conn:
            conn.execute(text("UPDATE events.events SET state='draft' WHERE id=:id"),{"id":created["id"]})
        assert client.get(path,headers=headers("actor-b")).status_code==404
