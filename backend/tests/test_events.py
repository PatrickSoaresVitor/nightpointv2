from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4
import httpx
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from app.bootstrap import create_app
from app.modules.events.infrastructure import PostgresEvents
from app.modules.identity.infrastructure import PostgresIdentityRepository
from app.modules.identity.domain import ExternalIdentity, ProfileValues
from app.platform.database import Database
from app.platform.test_guard import require_disposable
from tests.identity_fakes import FakeVerifier
from tests.test_database import engines as engines
from tests.test_identity_http import headers

pytestmark=pytest.mark.integration


def event_body(**overrides: Any) -> dict[str,Any]:
    return {"title":"Synthetic meetup","category_code":"jdm","starts_at":"2030-02-01T12:00:00+00:00",
        "timezone":"UTC","location_label":"Synthetic point","longitude":0.0,"latitude":0.0,**overrides}


@pytest.fixture
def event_store(engines: tuple[Engine,Database]) -> Iterator[tuple[Engine,Database,PostgresIdentityRepository]]:
    migrator,runtime=engines
    repo=PostgresIdentityRepository(runtime)
    for actor in ("actor-a","actor-b"):
        repo.enroll(ExternalIdentity("synthetic-issuer",actor),ProfileValues("Synthetic"))
    try:
        yield migrator,runtime,repo
    finally:
        with migrator.begin() as conn:
            require_disposable(conn)
            for table in ("events.creation_requests","events.events","accounts.profiles","accounts.identity_links","accounts.users"):
                conn.execute(text(f"DELETE FROM {table}"))


def test_event_create_detail_two_actors_idempotence_and_privacy(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    _,_,repo=event_store
    with TestClient(create_app(identity_test=(FakeVerifier(),repo))) as transport:
        client=cast(httpx.Client,transport)
        key=str(uuid4())
        created=client.post("/api/v1/events",headers={**headers(),"Idempotency-Key":key},json=event_body())
        assert created.status_code==201
        result=created.json()
        assert result["organizer_id"]==str(repo.resolve(ExternalIdentity("synthetic-issuer","actor-a")))
        assert created.headers["etag"]=='"1"' and created.headers["location"].endswith(result["id"])
        assert not {"email","issuer","subject","nickname","token"}.intersection(result)
        assert client.get(created.headers["location"],headers=headers("actor-b")).json()==result
        assert client.post("/api/v1/events",headers={**headers(),"Idempotency-Key":key},json=event_body()).json()==result
        assert client.post("/api/v1/events",headers={**headers(),"Idempotency-Key":key},json=event_body(title="Different")).status_code==409
        other=client.post("/api/v1/events",headers={**headers("actor-b"),"Idempotency-Key":key},json=event_body())
        assert other.status_code==201 and other.json()["id"]!=result["id"]
        assert client.get("/api/v1/events/"+str(uuid4()),headers=headers()).status_code==404


@pytest.mark.parametrize("invalid", [{"organizer_id":"forged"},{"author_id":"forged"},{"visibility":"unlisted"},
    {"state":"draft"},{"category_code":"unknown"},{"longitude":181.0},{"latitude":-91.0},
    {"starts_at":"2030-02-01T12:00:00"},{"timezone":"Invalid/Zone"},{"title":" "}])
def test_invalid_event_and_protected_fields(event_store: tuple[Engine,Database,PostgresIdentityRepository],invalid: dict[str,object]) -> None:
    migrator,_,repo=event_store
    with TestClient(create_app(identity_test=(FakeVerifier(),repo))) as transport:
        response=cast(httpx.Client,transport).post("/api/v1/events",headers={**headers(),"Idempotency-Key":str(uuid4())},json=event_body(**invalid))
        assert response.status_code==422
    with migrator.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM events.events"))==0


@pytest.mark.parametrize("missing", ["title","category_code","starts_at","timezone","location_label","longitude","latitude"])
def test_event_required_fields(event_store: tuple[Engine,Database,PostgresIdentityRepository],missing: str) -> None:
    _,_,repo=event_store
    body=event_body();body.pop(missing)
    with TestClient(create_app(identity_test=(FakeVerifier(),repo))) as transport:
        assert cast(httpx.Client,transport).post("/api/v1/events",headers={**headers(),"Idempotency-Key":str(uuid4())},json=body).status_code==422


def test_event_authentication_and_unprovisioned_have_no_side_effects(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    migrator,_,repo=event_store
    with migrator.begin() as conn:
        conn.execute(text("DELETE FROM accounts.profiles"));conn.execute(text("DELETE FROM accounts.identity_links"));conn.execute(text("DELETE FROM accounts.users"))
    with TestClient(create_app(identity_test=(FakeVerifier(),repo))) as transport:
        client=cast(httpx.Client,transport)
        assert client.post("/api/v1/events",json=event_body()).status_code==401
        assert client.post("/api/v1/events",headers={**headers(),"Idempotency-Key":str(uuid4())},json=event_body()).status_code==409
    with migrator.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM accounts.users"))==0


def test_concurrent_creation_receipt_rollback_and_grants(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    migrator,runtime,repo=event_store
    repository=PostgresEvents(runtime)
    from app.modules.events.domain import EventInput
    actor=repo.resolve(ExternalIdentity("synthetic-issuer","actor-a"));assert actor is not None
    values=EventInput("Synthetic","street",datetime(2000,1,1,tzinfo=timezone.utc),"UTC","Synthetic",0,0)
    key=uuid4()
    def create(_index: int) -> tuple[object,bool]:
        result,new=repository.create(actor,key,values)
        return result.id,new
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(create,range(6)))
    assert len({identifier for identifier,_ in results})==1 and sum(new for _,new in results)==1
    def interrupt(_conn: object,_cursor: object,statement: str,_parameters: object,_context: object,_many: bool) -> None:
        if statement.startswith("INSERT INTO events.creation_requests"):raise RuntimeError("Synthetic interruption")
    event.listen(runtime.engine,"before_cursor_execute",interrupt)
    try:
        with pytest.raises(RuntimeError):repository.create(actor,uuid4(),values)
    finally:event.remove(runtime.engine,"before_cursor_execute",interrupt)
    with migrator.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM events.events"))==1
        assert conn.scalar(text("SELECT count(*) FROM events.creation_requests"))==1
    for sql in ("DELETE FROM events.events","UPDATE events.events SET organizer_id=:id","TRUNCATE events.events",
                "UPDATE events.event_categories SET label='forged'","ALTER TABLE events.events ADD COLUMN forbidden text"):
        with pytest.raises(DBAPIError) as error:
            with runtime.transaction() as session:session.execute(text(sql),{"id":actor})
        assert getattr(error.value.orig,"sqlstate",None)=="42501"
    with pytest.raises(DBAPIError) as fk:
        with migrator.begin() as conn:conn.execute(text("DELETE FROM accounts.users WHERE id=:id"),{"id":actor})
    assert getattr(fk.value.orig,"sqlstate",None)=="23503"
