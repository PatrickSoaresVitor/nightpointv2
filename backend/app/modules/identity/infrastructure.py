"""Identity-owned PostgreSQL. Lookup is read-only; enrollment is an explicit command."""
from uuid import UUID, uuid4
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from app.platform.database import Database
from app.platform.telemetry import measure
from .domain import ExternalIdentity, MissingProfile, Profile, ProfileValues, ProfileChanges, StaleProfile

PROFILE_COLUMNS = "user_id,nickname,avatar_style,avatar_seed,version"


def to_profile(row: RowMapping) -> Profile:
    return Profile(UUID(str(row["user_id"])), ProfileValues(
        str(row["nickname"]), row["avatar_style"], row["avatar_seed"]), int(row["version"]))


class PostgresIdentityRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def resolve(self, identity: ExternalIdentity) -> UUID | None:
        with measure("identity.lookup"):
            with self.database.transaction() as session:
                with measure("identity.sql"):
                    existing = session.scalar(text("SELECT user_id FROM accounts.identity_links WHERE issuer=:issuer AND subject=:subject"),
                        {"issuer": identity.issuer, "subject": identity.subject})
                return UUID(str(existing)) if existing is not None else None

    def read(self, user_id: UUID) -> Profile | None:
        with self.database.transaction() as session:
            row = session.execute(text(f"SELECT {PROFILE_COLUMNS} FROM accounts.profiles WHERE user_id=:id"),
                                  {"id": user_id}).mappings().first()
            return to_profile(row) if row is not None else None

    def enroll(self, identity: ExternalIdentity, values: ProfileValues) -> tuple[Profile, bool]:
        with self.database.transaction() as session:
            key = f"{len(identity.issuer)}:{identity.issuer}{identity.subject}"
            session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})
            parameters = {"issuer": identity.issuer, "subject": identity.subject}
            existing = session.scalar(text("SELECT user_id FROM accounts.identity_links WHERE issuer=:issuer AND subject=:subject"), parameters)
            identifier = UUID(str(existing)) if existing is not None else uuid4()
            if existing is None:
                session.execute(text("INSERT INTO accounts.users(id) VALUES (:id)"), {"id": identifier})
                session.execute(text("INSERT INTO accounts.identity_links(issuer,subject,user_id) VALUES (:issuer,:subject,:id)"),
                    {**parameters, "id": identifier})
            inserted = session.execute(text("INSERT INTO accounts.profiles (user_id,nickname,avatar_style,avatar_seed) "
                f"VALUES (:id,:nickname,:style,:seed) ON CONFLICT (user_id) DO NOTHING RETURNING {PROFILE_COLUMNS}"),
                {"id": identifier, "nickname": values.nickname, "style": values.avatar_style,
                 "seed": values.avatar_seed}).mappings().first()
            row = inserted if inserted is not None else session.execute(text(
                f"SELECT {PROFILE_COLUMNS} FROM accounts.profiles WHERE user_id=:id"), {"id": identifier}).mappings().one()
            return to_profile(row), inserted is not None

    def update(self, user_id: UUID, values: ProfileChanges, expected_version: int) -> Profile:
        # Assign only validated allowlisted columns; omitted fields stay on the same SQL row/version.
        assignments = [field + "=:" + field for field in ("nickname", "avatar_style", "avatar_seed") if field in values.fields]
        with self.database.transaction() as session:
            row = session.execute(text("UPDATE accounts.profiles SET " + ",".join(assignments) +
                f",version=version+1,updated_at=now() WHERE user_id=:id AND version=:version RETURNING {PROFILE_COLUMNS}"),
                {"id": user_id, "version": expected_version, **values.fields}).mappings().first()
            if row is None:
                if session.scalar(text("SELECT user_id FROM accounts.profiles WHERE user_id=:id"), {"id": user_id}) is None:
                    raise MissingProfile()
                raise StaleProfile()
            return to_profile(row)
