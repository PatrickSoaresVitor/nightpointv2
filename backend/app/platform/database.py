from collections.abc import Generator
from contextlib import contextmanager
import time
from typing import Any
from sqlalchemy.pool import QueuePool

from sqlalchemy import create_engine, text, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.platform.telemetry import Telemetry, measure
from app.platform.config import Settings
from app.platform.test_guard import protect_engine, UnsafeTestTarget

COMPATIBLE_REVISIONS = frozenset({"0008_community"})


def compatible_revisions(revisions: set[str]) -> bool:
    return len(revisions) == 1 and revisions.issubset(COMPATIBLE_REVISIONS)


class Database:
    def __init__(self, settings: Settings) -> None:
        self.engine = create_engine(
            settings.database_url(), pool_pre_ping=True, pool_size=10,
            max_overflow=0, pool_timeout=0.5, hide_parameters=True,
            connect_args={"connect_timeout": 2, "options": "-c statement_timeout=2000 -c lock_timeout=1000"},
        )
        self.performance = Telemetry()
        @event.listens_for(self.engine,"connect")
        def connected(connection: object,record: object) -> None:
            self.performance.count("db.connected")
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.runtime_role = settings.db_user
        if settings.environment == "test":
            protect_engine(self.engine)

    @contextmanager
    def transaction(self) -> Generator[Session]:
        """One transaction per operation; commit on success, rollback on exception."""
        started = time.monotonic()
        try:
            with measure("db.transaction"):
                with self._sessions.begin() as session:
                    acquire = time.monotonic()
                    try:
                        with measure("db.acquire"):
                            session.connection()
                    finally:
                        self.performance.observe("db.acquire",time.monotonic()-acquire)
                    yield session
        finally:
            self.performance.observe("db.transaction",time.monotonic()-started)

    def diagnostics(self) -> dict[str, Any]:
        pool = self.engine.pool
        values: dict[str, Any] = {"metrics":self.performance.snapshot()}
        if isinstance(pool,QueuePool):
            values["pool"] = {"size":pool.size(),"checked_in":pool.checkedin(),
                              "checked_out":pool.checkedout(),"overflow":pool.overflow()}
        return values

    def ready(self) -> bool:
        try:
            with self.engine.connect() as conn:
                healthy = bool(conn.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='postgis') "
                    "AND to_regnamespace('nightpoint') IS NOT NULL "
                    "AND current_user=:runtime_role "
                    "AND public.PostGIS_Lib_Version() LIKE '3.%' "
                    "AND public.ST_DWithin("
                    "public.ST_SetSRID(public.ST_MakePoint(0,0),4326)::public.geography,"
                    "public.ST_SetSRID(public.ST_MakePoint(0,0),4326)::public.geography,1)"
                ), {"runtime_role": self.runtime_role}).scalar_one())
                revisions = set(conn.execute(text("SELECT version_num FROM migration.alembic_version")).scalars())
                return healthy and compatible_revisions(revisions)
        except (SQLAlchemyError, UnsafeTestTarget):
            return False

    def close(self) -> None:
        self.engine.dispose()
