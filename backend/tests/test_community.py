from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast
from uuid import UUID, uuid4
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import event as sql_event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from app.bootstrap import create_app
from app.modules.community.domain import Comment, validate_comment
from app.modules.community.presentation import CommentBody, CommentOutput
from app.modules.events.api import EventContext
from app.modules.events.application import EventService
from app.modules.events.infrastructure import PostgresEvents
from app.modules.community.application import CommunityService
from app.modules.community.infrastructure import PostgresCommunity
from app.modules.identity.api import VerifiedActor
from app.modules.identity.domain import ExternalIdentity
from app.modules.identity.infrastructure import PostgresIdentityRepository
from app.platform.database import Database
from app.platform.realtime import EventBus
from app.platform.test_guard import require_disposable
from tests.identity_fakes import FakeVerifier
from tests.test_database import engines as engines
from tests.test_events import event_store as event_store, event_body
from tests.test_identity_http import headers


@pytest.mark.parametrize('body', [{'text':' '}, {'text':'x\x00'}, {'text':'x'*1001},
    {'text':'ok','actor_id':str(uuid4())}, {'text':123}])
def test_comment_validation_and_forged_author_rejected(body: dict[str,Any]) -> None:
    with pytest.raises(ValueError): CommentBody.model_validate(body)


def test_multiline_comment_and_private_removal_projection() -> None:
    validate_comment('Synthetic\ncomment\ttext')
    author,organizer = uuid4(),uuid4()
    parent = EventContext(uuid4(),organizer,'published',1)
    comment = Comment(uuid4(),parent.id,author,'Synthetic',2,True,organizer)
    assert not comment.may_restore(author) and comment.may_restore(organizer)
    assert CommentOutput.of(comment,author,parent).text == ''
    assert CommentOutput.of(comment,organizer,parent).text == 'Synthetic'


def test_child_invalidation_is_bounded_without_changing_event_version() -> None:
    bus = EventBus()
    identifier = uuid4()
    subscription = bus.subscribe(identifier,uuid4(),7)
    for _ in range(20): bus.invalidate(identifier)
    assert 1 <= subscription.messages.qsize() <= 8
    while not subscription.messages.empty():
        change = subscription.messages.get_nowait()
        assert change.kind == 'resync' and change.version == 7
    assert subscription.version == 7
    bus.close()


@pytest.fixture
def community_store(event_store: tuple[Engine,Database,PostgresIdentityRepository]) -> Iterator[tuple[Engine,Database,PostgresIdentityRepository]]:
    migrator,_,_ = event_store
    try: yield event_store
    finally:
        with migrator.begin() as conn:
            require_disposable(conn)
            for table in ('creation_requests','comments','reactions'):
                conn.execute(text(f'DELETE FROM community.{table}'))


@pytest.mark.integration
def test_community_privacy_precedes_counts_pagination_and_receipt_lookup(community_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    _,runtime,identities = community_store
    statements: list[str] = []
    def record(_conn: object,_cursor: object,statement: str,_params: object,_context: object,_many: bool) -> None:
        if 'community.' in statement: statements.append(statement)
    with TestClient(create_app(identity_test=(FakeVerifier(),identities))) as transport:
        client = cast(httpx.Client,transport)
        created = client.post('/api/v1/events',headers={**headers(),'Idempotency-Key':str(uuid4())},json=event_body(visibility='owner_only'))
        assert created.status_code == 201
        base = created.headers['location']+'/community'
        sql_event.listen(runtime.engine,'before_cursor_execute',record)
        # create_app owns its own engine, so also verify with the guarded service
        actor = identities.resolve(ExternalIdentity('synthetic-issuer','actor-b'))
        assert actor is not None
        bus = EventBus()
        service = CommunityService(PostgresCommunity(runtime),EventService(PostgresEvents(runtime)),bus)
        from app.modules.events.api import InaccessibleEvent
        try:
            with pytest.raises(InaccessibleEvent): service.comments(lambda:VerifiedActor(actor),UUID(created.json()['id']),True,1,0)
            assert statements == []
        finally:
            sql_event.remove(runtime.engine,'before_cursor_execute',record);bus.close()
        for method,path,body in [('GET',base,None),('GET',base+'/comments?limit=1&include_removed=true',None),
            ('POST',base+'/comments',{'text':'Denied'}),('PUT',base+'/reactions/like',{'active':True})]:
            response = client.request(method,path,headers={**headers('actor-b'),'Idempotency-Key':str(uuid4())},json=body)
            assert response.status_code == 404
        assert client.get(base,headers=headers()).json()['likes'] == 0
        own_comment = client.post(base+'/comments',headers={**headers(),'Idempotency-Key':str(uuid4())},json={'text':'Private synthetic'})
        assert own_comment.status_code == 201
        public = client.post('/api/v1/events',headers={**headers(),'Idempotency-Key':str(uuid4())},json=event_body())
        assert public.status_code == 201
        wrong_parent = public.headers['location']+'/community/comments/'+own_comment.json()['id']
        assert client.get(wrong_parent,headers=headers('actor-b')).status_code == 404
        assert client.put(wrong_parent+'/visibility',headers={**headers(),'If-Match':'"1"'},json={'removed':True}).status_code == 404


@pytest.mark.integration
def test_reactions_comments_owner_moderation_restore_and_cancelled_replay(community_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    migrator,_,identities = community_store
    with TestClient(create_app(identity_test=(FakeVerifier(),identities))) as transport:
        client = cast(httpx.Client,transport)
        created = client.post('/api/v1/events',headers={**headers(),'Idempotency-Key':str(uuid4())},json=event_body())
        assert created.status_code == 201
        event_path = created.headers['location']; base = event_path+'/community'
        for kind in ('like','participation'):
            for _ in range(2): assert client.put(base+'/reactions/'+kind,headers=headers('actor-b'),json={'active':True}).status_code == 204
        summary = client.get(base,headers=headers('actor-b')).json()
        assert summary == {'likes':1,'participants':1,'liked':True,'participating':True}
        key = str(uuid4()); request_headers = {**headers('actor-b'),'Idempotency-Key':key}
        comment = client.post(base+'/comments',headers=request_headers,json={'text':'Synthetic\ncomment'})
        assert comment.status_code == 201 and comment.json()['mine'] and not comment.json()['organizer']
        path = comment.headers['location']
        assert client.post(base+'/comments',headers=request_headers,json={'text':'Synthetic\ncomment'}).status_code == 200
        assert client.post(base+'/comments',headers=request_headers,json={'text':'Changed'}).status_code == 409
        removed = client.put(path+'/visibility',headers={**headers(),'If-Match':'"1"'},json={'removed':True})
        assert removed.status_code == 200 and removed.json()['can_restore']
        assert client.get(path,headers=headers('actor-b')).status_code == 404
        assert client.get(base+'/comments?include_removed=true',headers=headers('actor-b')).json()['items'] == []
        assert client.put(path+'/visibility',headers={**headers('actor-b'),'If-Match':'"2"'},json={'removed':False}).status_code == 404
        assert client.put(path+'/visibility',headers={**headers(),'If-Match':'"1"'},json={'removed':False}).status_code == 412
        restored = client.put(path+'/visibility',headers={**headers(),'If-Match':'"2"'},json={'removed':False})
        assert restored.status_code == 200 and restored.json()['version'] == 3
        assert client.put(path+'/visibility',headers=headers('actor-b'),json={'removed':True}).status_code == 428
        assert client.get(base+'/comments?limit=51',headers=headers()).status_code == 422
        assert client.post(base+'/comments',headers={**headers(),'Idempotency-Key':str(uuid4())},json={'text':'ok','actor_id':str(uuid4())}).status_code == 422
        own_headers = {**headers(),'Idempotency-Key':str(uuid4())}
        own = client.post(base+'/comments',headers=own_headers,json={'text':'Owner synthetic'})
        assert own.status_code == 201
        assert client.post(event_path+'/cancel',headers={**headers(),'If-Match':'"1"'}).status_code == 200
        assert client.post(base+'/comments',headers=own_headers,json={'text':'Owner synthetic'}).status_code == 200
        assert client.post(base+'/comments',headers={**headers(),'Idempotency-Key':str(uuid4())},json={'text':'New'}).status_code == 409
        assert client.put(base+'/reactions/like',headers=headers(),json={'active':True}).status_code == 409
        with migrator.connect() as conn:
            assert conn.scalar(text('SELECT count(*) FROM community.comments')) == 2
            assert conn.scalar(text('SELECT count(*) FROM community.reactions')) == 2


@pytest.mark.integration
def test_concurrent_comment_receipts_and_runtime_grants(community_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    migrator,runtime,identities = community_store
    with TestClient(create_app(identity_test=(FakeVerifier(),identities))) as transport:
        created = cast(httpx.Client,transport).post('/api/v1/events',headers={**headers(),'Idempotency-Key':str(uuid4())},json=event_body())
        assert created.status_code == 201
    identifier = UUID(created.json()['id'])
    actor = identities.resolve(ExternalIdentity('synthetic-issuer','actor-a'))
    assert actor is not None
    bus = EventBus()
    service = CommunityService(PostgresCommunity(runtime),EventService(PostgresEvents(runtime)),bus)
    key = uuid4()
    def create(_: int) -> UUID:
        return service.create_comment(lambda:VerifiedActor(actor),identifier,key,'Synthetic')[1].id
    with ThreadPoolExecutor(max_workers=2) as executor: results = list(executor.map(create,range(2)))
    assert results[0] == results[1]
    with migrator.connect() as conn:
        assert conn.scalar(text('SELECT count(*) FROM community.comments')) == 1
    for statement in ('DELETE FROM community.comments','UPDATE community.comments SET actor_id=actor_id',
                      'UPDATE community.creation_requests SET fingerprint=fingerprint','CREATE TABLE community.denied(id integer)'):
        with pytest.raises(DBAPIError) as error:
            with runtime.transaction() as session: session.execute(text(statement))
        assert getattr(error.value.orig,'sqlstate',None) == '42501'
    bus.close()


@pytest.mark.integration
def test_event_policy_cannot_change_while_child_transaction_holds_access(community_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    migrator,runtime,identities = community_store
    with TestClient(create_app(identity_test=(FakeVerifier(),identities))) as transport:
        created = cast(httpx.Client,transport).post('/api/v1/events',headers={**headers(),'Idempotency-Key':str(uuid4())},json=event_body())
    assert created.status_code == 201
    identifier = UUID(created.json()['id'])
    actor = identities.resolve(ExternalIdentity('synthetic-issuer','actor-b'))
    assert actor is not None
    with EventService(PostgresEvents(runtime)).hold(actor,identifier):
        with pytest.raises(DBAPIError) as error:
            with migrator.begin() as conn:
                conn.execute(text("SET LOCAL lock_timeout='100ms'"))
                conn.execute(text("UPDATE events.events SET visibility='owner_only' WHERE id=:id"),{'id':identifier})
        assert getattr(error.value.orig,'sqlstate',None) == '55P03'


@pytest.mark.integration
def test_community_invalidation_occurs_after_commit_and_not_after_rollback(community_store: tuple[Engine,Database,PostgresIdentityRepository]) -> None:
    _,runtime,identities = community_store
    with TestClient(create_app(identity_test=(FakeVerifier(),identities))) as transport:
        created = cast(httpx.Client,transport).post('/api/v1/events',headers={**headers(),'Idempotency-Key':str(uuid4())},json=event_body())
    assert created.status_code == 201
    identifier = UUID(created.json()['id'])
    actor = identities.resolve(ExternalIdentity('synthetic-issuer','actor-a'))
    assert actor is not None
    calls: list[UUID] = []
    class CommitProbe:
        def invalidate(self,identifier: UUID) -> None:
            with runtime.transaction() as session:
                assert session.scalar(text('SELECT count(*) FROM community.comments WHERE event_id=:id'),{'id':identifier}) == 1
            calls.append(identifier)
    service = CommunityService(PostgresCommunity(runtime),EventService(PostgresEvents(runtime)),CommitProbe())
    service.create_comment(lambda:VerifiedActor(actor),identifier,uuid4(),'Committed')
    assert calls == [identifier]
    def interrupt(_conn: object,_cursor: object,statement: str,_params: object,_context: object,_many: bool) -> None:
        if statement.startswith('INSERT INTO community.comments'): raise RuntimeError('synthetic rollback')
    sql_event.listen(runtime.engine,'before_cursor_execute',interrupt)
    try:
        with pytest.raises(RuntimeError,match='synthetic rollback'):
            service.create_comment(lambda:VerifiedActor(actor),identifier,uuid4(),'Rolled back')
    finally: sql_event.remove(runtime.engine,'before_cursor_execute',interrupt)
    assert calls == [identifier]
