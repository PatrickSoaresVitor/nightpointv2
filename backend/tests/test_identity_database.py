from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
from typing import cast
import httpx

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from app.bootstrap import create_app
from app.modules.identity.domain import ExternalIdentity, ProfileValues, ProfileChanges, StaleProfile
from app.modules.identity.infrastructure import PostgresIdentityRepository
from app.platform.database import Database
from app.platform.test_guard import require_disposable
from tests.identity_fakes import FakeVerifier
from tests.test_database import engines as engines
from tests.test_identity_http import headers

pytestmark = pytest.mark.integration


@pytest.fixture
def store(engines: tuple[Engine, Database]) -> Iterator[tuple[PostgresIdentityRepository, Engine, Database]]:
    migrator, runtime = engines
    try:
        yield PostgresIdentityRepository(runtime), migrator, runtime
    finally:
        # Test-only controlled cleanup after receipt verification on this same connection.
        with migrator.begin() as conn:
            require_disposable(conn)
            for table in ("profiles", "identity_links", "users"):
                conn.execute(text(f"DELETE FROM accounts.{table}"))


def test_real_idempotent_identity_incomplete_recovery_and_external_link(store: tuple[PostgresIdentityRepository, Engine, Database]) -> None:
    repo, migrator, _ = store
    identity = ExternalIdentity("synthetic-issuer", "synthetic-a")
    assert repo.resolve(identity) is None
    # Recover the incomplete state from the previous release, without a production helper.
    actor = uuid4()
    with migrator.begin() as conn:
        conn.execute(text("INSERT INTO accounts.users(id) VALUES(:id)"), {"id": actor})
        conn.execute(text("INSERT INTO accounts.identity_links(issuer,subject,user_id) VALUES(:issuer,:subject,:id)"),
                     {"issuer": identity.issuer, "subject": identity.subject, "id": actor})
    assert repo.resolve(identity) == actor and repo.read(actor) is None
    profile, created = repo.enroll(identity, ProfileValues("Same nickname", "legacy-style", "legacy-seed"))
    assert created and profile.user_id == actor
    repeated, created = repo.enroll(identity, ProfileValues("Ignored retry"))
    assert not created and repeated == profile
    other = repo.enroll(ExternalIdentity(identity.issuer, "synthetic-b"), ProfileValues("Same nickname"))[0].user_id
    issuer_other = repo.enroll(ExternalIdentity("different-issuer", identity.subject), ProfileValues("Same nickname"))[0].user_id
    assert len({actor, other, issuer_other}) == 3


def test_real_concurrent_identity_and_profile_unique(store: tuple[PostgresIdentityRepository, Engine, Database]) -> None:
    repo, _, _ = store
    identity = ExternalIdentity("synthetic-issuer", "synthetic-concurrent")
    with ThreadPoolExecutor(max_workers=6) as pool:
        def enroll(_index: int) -> tuple[object, bool]:
            profile, created = repo.enroll(identity, ProfileValues("Concurrent"))
            return profile.user_id, created
        results = list(pool.map(enroll, range(6)))
    assert sum(created for _, created in results) == 1
    actors = [repo.resolve(identity)]
    assert actors[0] is not None and len({actor for actor, _ in results}) == 1
    old = repo.read(actors[0])
    assert old is not None
    def update(_index: int) -> bool:
        try:
            repo.update(old.user_id, ProfileChanges({"nickname": "Changed"}), old.version)
            return True
        except StaleProfile:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(update, range(2))) == 1


def test_real_identity_atomic_rollback_and_retry(store: tuple[PostgresIdentityRepository, Engine, Database]) -> None:
    repo, migrator, runtime = store
    def interrupt(_conn: object, _cursor: object, statement: str, _parameters: object, _context: object, _many: bool) -> None:
        if statement.startswith("INSERT INTO accounts.identity_links"):
            raise RuntimeError("Synthetic interruption")
    event.listen(runtime.engine, "before_cursor_execute", interrupt)
    identity = ExternalIdentity("synthetic-issuer", "interrupted")
    try:
        with pytest.raises(RuntimeError, match="Synthetic interruption"):
            repo.enroll(identity, ProfileValues("Recovered"))
    finally:
        event.remove(runtime.engine, "before_cursor_execute", interrupt)
    with migrator.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM accounts.users")) == 0
        assert conn.scalar(text("SELECT count(*) FROM accounts.identity_links")) == 0
    assert repo.resolve(identity) is None
    assert repo.enroll(identity, ProfileValues("Recovered"))[1]


def test_real_profile_interruption_rolls_back_and_recovers(store: tuple[PostgresIdentityRepository, Engine, Database]) -> None:
    repo, _, runtime = store
    identity = ExternalIdentity("synthetic-issuer", "profile-interruption")
    def interrupt(_conn: object, _cursor: object, statement: str, _parameters: object, _context: object, _many: bool) -> None:
        if statement.startswith("INSERT INTO accounts.profiles"):
            raise RuntimeError("Synthetic interruption after SQL")
    event.listen(runtime.engine, "after_cursor_execute", interrupt)
    try:
        with pytest.raises(RuntimeError, match="Synthetic interruption"):
            repo.enroll(identity, ProfileValues("Uncommitted"))
    finally:
        event.remove(runtime.engine, "after_cursor_execute", interrupt)
    assert repo.resolve(identity) is None
    assert repo.enroll(identity, ProfileValues("Recovered"))[1]


def test_real_readiness_fails_closed_for_other_revisions(store: tuple[PostgresIdentityRepository, Engine, Database]) -> None:
    _, migrator, runtime = store
    try:
        for revision in ("0007_garage", "0006_event_management", "0005_events", "0003_identity", "0002_privileges", "future_unreviewed"):
            with migrator.begin() as conn:
                conn.execute(text("UPDATE migration.alembic_version SET version_num=:revision"), {"revision": revision})
            assert not runtime.ready()
    finally:
        with migrator.begin() as conn:
            conn.execute(text("UPDATE migration.alembic_version SET version_num='0008_community'"))
    assert runtime.ready()


def test_real_constraints_and_explicit_column_privileges(store: tuple[PostgresIdentityRepository, Engine, Database]) -> None:
    repo, migrator, runtime = store
    actor = repo.enroll(ExternalIdentity("synthetic-issuer", "synthetic-a"), ProfileValues("Synthetic"))[0].user_id
    statements = [
        ("INSERT INTO accounts.identity_links(issuer,subject,user_id) VALUES('synthetic-issuer','synthetic-a',:id)", "23505"),
        ("INSERT INTO accounts.identity_links(issuer,subject,user_id) VALUES('synthetic-issuer','unknown',:unknown)", "23503"),
        ("UPDATE accounts.profiles SET nickname='' WHERE user_id=:id", "23514"),
        ("UPDATE accounts.users SET state='active' WHERE id=:id", "42501"),
        ("UPDATE accounts.identity_links SET subject='forged' WHERE user_id=:id", "42501"),
        ("UPDATE accounts.profiles SET user_id=:unknown WHERE user_id=:id", "42501"),
        ("INSERT INTO accounts.users(id,state) VALUES(:unknown,'active')", "42501"),
        ("DELETE FROM accounts.profiles WHERE user_id=:id", "42501"),
        ("TRUNCATE accounts.users", "42501"),
        ("ALTER TABLE accounts.profiles ADD COLUMN forbidden text", "42501"),
    ]
    for statement, sqlstate in statements:
        with pytest.raises(DBAPIError) as error:
            with runtime.transaction() as session:
                session.execute(text(statement), {"id": actor, "unknown": uuid4()})
        assert getattr(error.value.orig, "sqlstate", None) == sqlstate, statement
    with migrator.connect() as conn:
        owners = conn.execute(text("SELECT tableowner FROM pg_tables WHERE schemaname='accounts'")).scalars().all()
        assert owners == ["np_migrator"] * 3
        columns = set(conn.execute(text("SELECT column_name FROM information_schema.columns "
                                       "WHERE table_schema='accounts'")).scalars())
        assert not columns.intersection({"email", "password", "token", "role"})


def test_real_http_two_actor_authorization_and_dto(store: tuple[PostgresIdentityRepository, Engine, Database]) -> None:
    repo, _, runtime = store
    app = create_app(identity_test=(FakeVerifier(), repo))
    with TestClient(app) as transport:
        client = cast(httpx.Client, transport)
        a = client.put("/api/v1/me/profile", headers=headers(), json={"nickname": "A"})
        b = client.put("/api/v1/me/profile", headers=headers("actor-b"), json={"nickname": "B"})
        assert a.status_code == b.status_code == 201
        assert a.json()["user_id"] != b.json()["user_id"]
        route = "/api/v1/profiles/" + a.json()["user_id"]
        assert client.get(route, headers=headers("actor-b")).status_code == 404
        assert client.patch(route, headers={**headers("actor-b"), "If-Match": '"1"'}, json={"nickname": "Forbidden"}).status_code == 404
        assert client.get(route, headers=headers()).json() == a.json()
        assert set(a.json()) == {"user_id", "nickname", "avatar_style", "avatar_seed", "version"}
        assert client.patch("/api/v1/me/profile", headers={**headers(), "If-Match": '"1"'},
                            json={"nickname": "Updated"}).status_code == 200
    assert runtime.ready()


@pytest.mark.parametrize("route", ["/api/v1/me/profile", "/api/v1/profiles/{id}"])
@pytest.mark.parametrize("expected", [1,2])
def test_http_patch_deterministic_intervening_version(store: tuple[PostgresIdentityRepository, Engine, Database],
    route: str, expected: int) -> None:
    repo, _, runtime = store
    blocked, release = Event(), Event()
    def pause(_conn: object, _cursor: object, statement: str, parameters: object, _context: object, _many: bool) -> None:
        if statement.startswith("UPDATE accounts.profiles") and isinstance(parameters, dict) and cast(dict[str, object],parameters).get("nickname") == "Late":
            blocked.set()
            assert release.wait(5), "Competing update did not complete"
    app = create_app(identity_test=(FakeVerifier(),repo))
    with TestClient(app) as transport:
        client = cast(httpx.Client,transport)
        initial = client.put("/api/v1/me/profile", headers=headers(), json={"nickname":"Original","avatar_seed":"old"})
        path = route.replace("{id}",initial.json()["user_id"])
        event.listen(runtime.engine,"before_cursor_execute",pause)
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                late = pool.submit(client.patch,path,headers={**headers(),"If-Match":f'"{expected}"'},json={"nickname":"Late"})
                try:
                    assert blocked.wait(5)
                    competing = client.patch(path,headers={**headers(),"If-Match":'"1"'},json={"avatar_seed":"new"})
                    assert competing.status_code == 200 and competing.headers["etag"] == '"2"'
                finally:
                    release.set()
                result = late.result(timeout=5)
        finally:
            event.remove(runtime.engine,"before_cursor_execute",pause)
        current = client.get(path,headers=headers())
        assert current.json()["avatar_seed"] == "new"
        if expected == 1:
            assert result.status_code == 412 and "etag" not in result.headers
            assert current.json() == competing.json() and current.headers["etag"] == '"2"'
        else:
            assert result.status_code == 200 and result.headers["etag"] == '"3"'
            assert current.json()["nickname"] == "Late" and current.json()["version"] == 3


def test_real_lookup_navigation_and_rejections_only_select(store: tuple[PostgresIdentityRepository, Engine, Database]) -> None:
    repo, migrator, runtime = store
    statements: list[str] = []
    def record(_conn: object, _cursor: object, statement: str, _parameters: object, _context: object, _many: bool) -> None:
        statements.append(statement)
    event.listen(runtime.engine,"before_cursor_execute",record)
    try:
        with TestClient(create_app(identity_test=(FakeVerifier(),repo))) as transport:
            client = cast(httpx.Client,transport)
            for path in ("/api/v1/session","/api/v1/me/profile","/api/v1/profiles/"+str(uuid4())):
                assert client.get(path,headers=headers()).status_code == 409
            assert client.patch("/api/v1/me/profile",headers={**headers(),"If-Match":'"1"'},json={"nickname":"New"}).status_code == 409
            assert client.put("/api/v1/me/profile",headers=headers(),json={"nickname":"New","role":"admin"}).status_code == 422
        assert statements and all(s.lstrip().upper().startswith("SELECT") for s in statements)
        with migrator.connect() as conn:
            for table in ("users","identity_links","profiles"):
                assert conn.scalar(text(f"SELECT count(*) FROM accounts.{table}")) == 0
    finally:
        event.remove(runtime.engine,"before_cursor_execute",record)


@pytest.mark.parametrize("value,valid", [("Night São 🚗",True),("\u00a0",False),("\u2003",False),
    ("a\u0085b",False),("a\x7fb",False),("a\u009fb",False),("e\u0301",True),(" a ",True),("a\u2028b",True),("\u3000",False)])
def test_real_text_policy_matches_http_domain_and_constraint(store: tuple[PostgresIdentityRepository, Engine, Database],value: str,valid: bool) -> None:
    repo, _, runtime = store
    actor = repo.enroll(ExternalIdentity("synthetic-issuer","text"),ProfileValues("Original"))[0].user_id
    if valid:
        with runtime.transaction() as session:
            session.execute(text("UPDATE accounts.profiles SET nickname=:value WHERE user_id=:id"),{"value":value,"id":actor})
        assert repo.read(actor) is not None
    else:
        with pytest.raises(DBAPIError) as error:
            with runtime.transaction() as session:
                session.execute(text("UPDATE accounts.profiles SET nickname=:value WHERE user_id=:id"),{"value":value,"id":actor})
        assert getattr(error.value.orig,"sqlstate",None) == "23514"


def test_profile_projection_does_not_read_new_private_column(store: tuple[PostgresIdentityRepository, Engine, Database]) -> None:
    repo, migrator, _ = store
    identity = ExternalIdentity("synthetic-issuer","projection")
    actor = repo.enroll(identity,ProfileValues("Synthetic"))[0].user_id
    with migrator.begin() as conn:
        conn.execute(text("ALTER TABLE accounts.profiles ADD COLUMN private_audit_note text"))
        conn.execute(text("REVOKE SELECT ON accounts.profiles FROM np_runtime"))
        conn.execute(text("GRANT SELECT(user_id,nickname,avatar_style,avatar_seed,version) ON accounts.profiles TO np_runtime"))
    try:
        assert repo.read(actor) is not None
        assert repo.enroll(identity,ProfileValues("Ignored"))[0].user_id == actor
        assert repo.update(actor,ProfileChanges({"nickname":"Changed"}),1).version == 2
    finally:
        with migrator.begin() as conn:
            conn.execute(text("GRANT SELECT ON accounts.profiles TO np_runtime"))
            conn.execute(text("ALTER TABLE accounts.profiles DROP COLUMN private_audit_note"))
