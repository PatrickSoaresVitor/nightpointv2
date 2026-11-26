from collections.abc import Iterator
import os
from pathlib import Path
import subprocess
import time
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.platform.config import load_settings
from app.platform.database import Database
from app.platform.test_guard import protect_engine, load_receipt, verify_connection, UnsafeTestTarget
from sqlalchemy import event

pytestmark = pytest.mark.integration


@pytest.fixture
def engines() -> Iterator[tuple[Engine, Database]]:
    settings = load_settings()
    assert settings.environment == "test" and settings.db_host == "db"
    assert os.environ.get("NP_MIGRATOR_PASSWORD_FILE")
    password = Path(os.environ["NP_MIGRATOR_PASSWORD_FILE"]).read_text().strip()
    migration_url = settings.database_url().set(username="np_migrator", password=password)
    migrator = create_engine(migration_url, hide_parameters=True)
    protect_engine(migrator)
    runtime = Database(settings)
    try:
        # The fixture must meet the same actual runtime readiness as the API,
        # including native PostGIS initialization, before evaluating behavior.
        # This is bounded setup, not a retry of a failed test or a timeout change.
        deadline=time.monotonic()+15
        while not runtime.ready():
            if time.monotonic()>=deadline:
                raise RuntimeError('Disposable runtime did not become ready for the fixture')
            time.sleep(.1)
        yield migrator, runtime
    finally:
        runtime.close()
        migrator.dispose()


def test_postgis_identity_readiness_and_permissions(engines: tuple[Engine, Database]) -> None:
    _, runtime = engines
    assert runtime.ready()
    with runtime.engine.connect() as conn:
        assert conn.scalar(text("SELECT current_user")) == "np_runtime"
        version = conn.scalar(text("SELECT PostGIS_Lib_Version()"))
        assert isinstance(version, str) and version.startswith("3.")
        flags = conn.execute(text("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
                                  "FROM pg_roles WHERE rolname=current_user")).one()
        assert not any(flags)
    forbidden = [
        "CREATE TABLE nightpoint.forbidden(id int)",
        "CREATE TABLE public.forbidden(id int)",
        "CREATE SCHEMA forbidden",
        "CREATE TEMP TABLE forbidden(id int)",
        "CREATE ROLE forbidden",
        "ALTER ROLE np_runtime SUPERUSER",
        "SET ROLE np_migrator",
        "CREATE EXTENSION postgis_raster",
        "UPDATE migration.alembic_version SET version_num='invalid'",
    ]
    for statement in forbidden:
        with pytest.raises(DBAPIError) as error:
            with runtime.engine.begin() as conn:
                conn.execute(text(statement))
        assert getattr(error.value.orig, "sqlstate", None) == "42501"


def test_bootstrap_completion_is_not_a_runtime_attestation_bypass(engines: tuple[Engine, Database]) -> None:
    migrator, runtime = engines
    for engine in (migrator, runtime.engine):
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regprocedure('test_guard.bootstrap_complete()') IS NOT NULL")) is True
            assert connection.scalar(text("SELECT has_function_privilege(current_user,'test_guard.bootstrap_complete()','EXECUTE')")) is False
        with pytest.raises(DBAPIError) as error:
            with engine.begin() as connection:
                connection.execute(text("SELECT test_guard.bootstrap_complete()"))
        assert getattr(error.value.orig, "sqlstate", None) == "42501"


def test_readiness_requires_spatial_runtime_not_just_extension_metadata(engines: tuple[Engine, Database]) -> None:
    _, runtime = engines
    def unavailable(_connection: object,_cursor: object,statement: str,_parameters: object,_context: object,_many: bool) -> None:
        if 'ST_DWithin' in statement:
            raise SQLAlchemyError('Synthetic spatial runtime unavailable')
    event.listen(runtime.engine,'before_cursor_execute',unavailable)
    try:
        assert runtime.ready() is False
    finally:
        event.remove(runtime.engine,'before_cursor_execute',unavailable)
    assert runtime.ready() is True


def test_spatial_constraints_index_and_transaction_rollback(engines: tuple[Engine, Database]) -> None:
    migrator, runtime = engines
    name = "probe_" + uuid4().hex
    # Names are generated hex identifiers, never user input. Only this fixture is dropped.
    table = f"nightpoint.{name}"
    with migrator.begin() as conn:
        conn.execute(text(f"CREATE TABLE {table} (id integer PRIMARY KEY, "
                          "label text UNIQUE NOT NULL, point geometry(Point,4326) NOT NULL, "
                          f"parent_id integer REFERENCES {table}(id), "
                          "CHECK(ST_X(point) BETWEEN -180 AND 180 AND ST_Y(point) BETWEEN -90 AND 90))"))
        conn.execute(text(f"CREATE INDEX {name}_geog_idx ON {table} USING gist((point::geography))"))
        conn.execute(text(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO np_runtime"))
    try:
        with runtime.transaction() as session:
            session.execute(text(f"INSERT INTO {table} VALUES (1,'synthetic',ST_SetSRID(ST_Point(0,0),4326))"))
        with pytest.raises(RuntimeError):
            with runtime.transaction() as session:
                session.execute(text(f"INSERT INTO {table} VALUES (2,'rollback',ST_SetSRID(ST_Point(1,1),4326))"))
                raise RuntimeError("Synthetic failure")
        with runtime.engine.connect() as conn:
            assert conn.scalar(text(f"SELECT count(*) FROM {table}")) == 1
            assert conn.scalar(text(f"SELECT count(*) FROM {table} WHERE "
                                    "ST_DWithin(point::geography,ST_SetSRID(ST_Point(0,0),4326)::geography,100)")) == 1
        with pytest.raises(DBAPIError) as unique_error:
            with runtime.transaction() as session:
                session.execute(text(f"INSERT INTO {table} VALUES (3,'synthetic',ST_SetSRID(ST_Point(0,0),4326))"))
        assert getattr(unique_error.value.orig, "sqlstate", None) == "23505"
        with runtime.transaction() as session:
            session.execute(text(f"INSERT INTO {table}(id,label,point) VALUES "
                                 "(4,'outside',ST_SetSRID(ST_Point(1,0),4326)),"
                                 "(5,'inside',ST_SetSRID(ST_Point(0.0001,0),4326))"))
        spatial_filter = "ST_DWithin(point::geography,ST_SetSRID(ST_Point(0,0),4326)::geography,100)"
        with runtime.engine.connect() as conn:
            assert conn.execute(text(f"SELECT id FROM {table} WHERE {spatial_filter} ORDER BY id")).scalars().all() == [1, 5]
        for statement, sqlstate in [
            (f"UPDATE {table} SET parent_id=9999 WHERE id=1", "23503"),
            (f"UPDATE {table} SET point=ST_SetSRID(ST_Point(181,0),4326) WHERE id=1", "23514"),
            (f"TRUNCATE {table}", "42501"),
        ]:
            with pytest.raises(DBAPIError) as error:
                with runtime.transaction() as session:
                    session.execute(text(statement))
            assert getattr(error.value.orig, "sqlstate", None) == sqlstate
        with migrator.begin() as conn:
            conn.execute(text(f"INSERT INTO {table} SELECT n, 'fixture-'||n, "
                              "ST_SetSRID(ST_Point((n%360)-180, (n%180)-90),4326) FROM generate_series(10,3010) n"))
            conn.execute(text(f"ANALYZE {table}"))
            plan = conn.execute(text(f"EXPLAIN SELECT * FROM {table} WHERE {spatial_filter}")).scalars().all()
            assert any(f"{name}_geog_idx" in str(line) for line in plan)
    finally:
        with migrator.begin() as conn:
            conn.execute(text(f"DROP TABLE {table}"))


def test_migrations_downgrade_upgrade_and_readiness(engines: tuple[Engine, Database]) -> None:
    _, runtime = engines
    environment = dict(os.environ)
    environment["NP_DB_USER"] = "np_migrator"
    environment["NP_DB_PASSWORD_FILE"] = environment["NP_MIGRATOR_PASSWORD_FILE"]
    try:
        subprocess.run(["python", "-m", "alembic", "downgrade", "base"], env=environment, check=True)
        assert not runtime.ready()
    finally:
        subprocess.run(["python", "-m", "alembic", "upgrade", "head"], env=environment, check=True)
    assert runtime.ready()


def test_database_unavailable_fails_readiness() -> None:
    configuration = load_settings()
    assert configuration.environment == "test" and configuration.db_host == "db"
    unavailable = Database(configuration.model_copy(update={"db_port": 1}))
    try:
        assert unavailable.ready() is False
    finally:
        unavailable.close()


def test_wrong_connected_database_is_refused_before_mutation(engines: tuple[Engine, Database]) -> None:
    migrator, _ = engines
    wrong_url = migrator.url.set(database="nightpoint_shadow")
    observer = create_engine(wrong_url, hide_parameters=True)
    blocked = create_engine(wrong_url, hide_parameters=True)
    statements: list[str] = []

    @event.listens_for(blocked, "before_cursor_execute")
    def record(_conn: object, _cursor: object, statement: str, _parameters: object, _context: object, _many: bool) -> None:
        statements.append(statement)

    try:
        with observer.connect() as conn:
            before = conn.execute(text("SELECT nspname FROM pg_namespace ORDER BY nspname")).scalars().all()
        protect_engine(blocked)
        with pytest.raises(UnsafeTestTarget):
            with blocked.begin() as conn:
                conn.execute(text("CREATE SCHEMA must_never_execute"))
        assert statements and all(s.lstrip().upper().startswith("SELECT") for s in statements)
        with observer.connect() as conn:
            assert conn.execute(text("SELECT nspname FROM pg_namespace ORDER BY nspname")).scalars().all() == before
    finally:
        blocked.dispose()
        observer.dispose()


@pytest.mark.parametrize("field,value", [("system_identifier", "1"), ("database_oid", 1), ("token_hash", "0" * 64)])
def test_server_attestation_mismatch_refuses_target(engines: tuple[Engine, Database], field: str, value: object) -> None:
    migrator, _ = engines
    receipt = load_receipt().model_copy(update={field: value})
    with migrator.connect() as connection:
        with pytest.raises(UnsafeTestTarget):
            verify_connection(connection, receipt)


def test_alembic_refuses_unproven_roundtrip_without_mutation(engines: tuple[Engine, Database]) -> None:
    migrator, runtime = engines
    with migrator.connect() as conn:
        before = conn.scalar(text("SELECT version_num FROM migration.alembic_version"))
    environment = dict(os.environ, NP_DB_USER="np_migrator", NP_DB_PASSWORD_FILE=os.environ["NP_MIGRATOR_PASSWORD_FILE"],
                       NP_TEST_RECEIPT_FILE="/nonexistent-proof.json")
    result = subprocess.run(["python", "-m", "alembic", "downgrade", "base"], env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and "Disposable database receipt is required" in result.stderr
    with migrator.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM migration.alembic_version")) == before
    assert runtime.ready()


def test_future_tables_default_deny_and_revision_read_only(engines: tuple[Engine, Database]) -> None:
    migrator, runtime = engines
    name = "restricted_" + uuid4().hex
    with migrator.begin() as conn:
        conn.execute(text(f"CREATE TABLE nightpoint.{name}(id integer)"))
    try:
        for operation in (f"SELECT * FROM nightpoint.{name}", f"INSERT INTO nightpoint.{name} VALUES(1)"):
            with pytest.raises(DBAPIError) as error:
                with runtime.engine.begin() as conn:
                    conn.execute(text(operation))
            assert getattr(error.value.orig, "sqlstate", None) == "42501"
        with runtime.engine.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM migration.alembic_version")) == "0008_community"
    finally:
        with migrator.begin() as conn:
            conn.execute(text(f"DROP TABLE nightpoint.{name}"))


def test_readiness_pool_wait_is_bounded(engines: tuple[Engine, Database]) -> None:
    _, runtime = engines
    original = runtime.engine
    runtime.engine = create_engine(original.url, pool_size=1, max_overflow=0, pool_timeout=0.1, hide_parameters=True)
    protect_engine(runtime.engine)
    try:
        with runtime.engine.connect():
            start = time.monotonic()
            assert runtime.ready() is False
            assert time.monotonic() - start < 2
    finally:
        runtime.engine.dispose()
        runtime.engine = original
