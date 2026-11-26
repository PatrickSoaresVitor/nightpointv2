import base64
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4
import httpx
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from app.bootstrap import create_app
from app.modules.discovery.domain import CursorPosition, InvalidCursor, NearbyQuery
from app.modules.discovery.infrastructure import SignedCursor
from app.modules.events.infrastructure import PostgresEvents
from app.modules.identity.infrastructure import PostgresIdentityRepository
from app.platform.database import Database
from tests.identity_fakes import FakeVerifier
from tests.test_events import event_store as event_store, event_body
from tests.test_database import engines as engines
from tests.test_identity_http import headers


def search_body(**changes: Any) -> dict[str,Any]:
    return {"longitude":0.0,"latitude":0.0,"radius_m":1000.0,"from_ts":"2030-02-01T00:00:00Z",
        "until_ts":"2030-02-10T00:00:00Z","limit":25,**changes}


@pytest.mark.integration
def test_real_nearby_filters_distance_order_cursor_and_no_origin_writes(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    migrator,runtime,repo=event_store
    app=create_app(identity_test=(FakeVerifier(),repo))
    with TestClient(app) as transport:
        client=cast(httpx.Client,transport)
        ids: list[str]=[]
        for body in (event_body(title="A"),event_body(title="B"),event_body(title="Outside",longitude=0.02),
            event_body(title="Past",starts_at="2030-01-01T12:00:00Z"),event_body(title="Other category",category_code="drift"),
            event_body(title="Hidden")):
            response=client.post("/api/v1/events",headers={**headers(),"Idempotency-Key":str(uuid4())},json=body)
            assert response.status_code==201
            ids.append(response.json()["id"])
        with migrator.begin() as conn:
            conn.execute(text("UPDATE events.events SET visibility='unlisted' WHERE id=:id"),{"id":ids[-1]})
        statements: list[str]=[]
        def record(_conn: object,_cursor: object,sql: str,_parameters: object,_context: object,_many: bool) -> None:statements.append(sql)
        event.listen(runtime.engine,"before_cursor_execute",record)
        try:
            # The projection's real SQL path is also instrumented independently of HTTP's own pool.
            from app.modules.events.api import SearchSpec
            direct=PostgresEvents(runtime).nearby(SearchSpec(0,0,1000,datetime(2030,2,1,tzinfo=timezone.utc),datetime(2030,2,10,tzinfo=timezone.utc),"jdm",datetime.now(timezone.utc)),25)
            assert len(direct)==2 and statements and all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
        finally:event.remove(runtime.engine,"before_cursor_execute",record)
        first=client.post("/api/v1/discovery/nearby",headers=headers(),json=search_body(limit=1,category_code="jdm"))
        assert first.status_code==200
        page=first.json();assert len(page["items"])==1 and page["next_cursor"]
        second=client.post("/api/v1/discovery/nearby",headers=headers(),json=search_body(limit=1,category_code="jdm",cursor=page["next_cursor"]))
        combined=page["items"]+second.json()["items"]
        assert [item["id"] for item in combined]==sorted(ids[:2])
        assert all(item["distance_m"]==0 for item in combined) and second.json()["next_cursor"] is None
        assert all(not {"organizer_id","email","subject","issuer","latitude","longitude"}.intersection(item) for item in combined)
        assert client.post("/api/v1/discovery/nearby",headers=headers(),json=search_body(limit=1,category_code="jdm",radius_m=2000.0,cursor=page["next_cursor"])).status_code==422
        assert client.post("/api/v1/discovery/nearby",headers=headers("actor-b"),json=search_body(limit=1,category_code="jdm",cursor=page["next_cursor"])).status_code==422
        assert client.get("/api/v1/events/"+ids[-1],headers=headers()).status_code==404


@pytest.mark.integration
def test_real_metre_boundary_and_longitude_latitude(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    migrator,_,repo=event_store
    with TestClient(create_app(identity_test=(FakeVerifier(),repo))) as transport:
        client=cast(httpx.Client,transport)
        ids: list[str]=[]
        for distance in (999.9,1000.1):
            response=client.post("/api/v1/events",headers={**headers(),"Idempotency-Key":str(uuid4())},json=event_body())
            identifier=response.json()["id"];ids.append(identifier)
            with migrator.begin() as conn:
                conn.execute(text("UPDATE events.events SET location=ST_Project(ST_SetSRID(ST_MakePoint(12,34),4326)::geography,:distance,radians(90)) WHERE id=:id"),{"distance":distance,"id":identifier})
        result=client.post("/api/v1/discovery/nearby",headers=headers(),json=search_body(longitude=12.0,latitude=34.0)).json()
        assert [row["id"] for row in result["items"]]==[ids[0]]
        assert result["items"][0]["distance_m"]==pytest.approx(999.9,abs=0.002)
        swapped=client.post("/api/v1/discovery/nearby",headers=headers(),json=search_body(longitude=34.0,latitude=12.0))
        assert swapped.json()["items"]==[]


@pytest.mark.parametrize("changes", [{"longitude":181.0},{"latitude":-91.0},{"radius_m":50001.0},{"limit":51},
    {"from_ts":"2030-02-10T00:00:00Z","until_ts":"2030-02-01T00:00:00Z"},
    {"from_ts":"2030-02-01T00:00:00"},{"until_ts":"2031-02-01T00:00:00Z"},{"category_code":"invalid"}])
def test_query_invalid(changes: dict[str,Any]) -> None:
    from app.modules.discovery.presentation import NearbyInput
    with pytest.raises(ValueError):NearbyInput.model_validate(search_body(**changes))


def test_cursor_is_bound_signed_private_and_expiring(monkeypatch: pytest.MonkeyPatch) -> None:
    codec=SignedCursor()
    actor=uuid4()
    query=NearbyQuery(12.123456,-34.654321,1000,datetime(2030,2,1,tzinfo=timezone.utc),datetime(2030,2,2,tzinfo=timezone.utc))
    position=CursorPosition(datetime.now(timezone.utc),100,uuid4())
    token=codec.encode(position,query.binding(actor))
    assert codec.decode(token,query.binding(actor))==position
    readable=base64.urlsafe_b64decode(token+"="*(-len(token)%4))
    assert b"12.123456" not in readable and b"34.654321" not in readable
    for candidate in ("invalid",token[:-10]+"aaaaaaaaaa"):
        with pytest.raises(InvalidCursor):codec.decode(candidate,query.binding(actor))
    with pytest.raises(InvalidCursor):codec.decode(token,query.binding(uuid4()))
    import time
    now=time.time()
    monkeypatch.setattr("app.modules.discovery.infrastructure.time.time",lambda:now+301)
    with pytest.raises(InvalidCursor):codec.decode(token,query.binding(actor))
