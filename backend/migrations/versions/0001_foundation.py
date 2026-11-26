"""Local foundation schema, grants and PostGIS precondition; no business model."""
from alembic import op
from app.platform.test_guard import require_disposable

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extension installation is privileged bootstrap, never runtime/migrator.
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_extension WHERE extname='postgis') THEN
            RAISE EXCEPTION 'PostGIS bootstrap required';
        END IF;
    END $$""")
    op.execute("CREATE SCHEMA nightpoint AUTHORIZATION np_migrator")
    op.execute("REVOKE ALL ON SCHEMA nightpoint FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA nightpoint TO np_runtime")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE np_migrator IN SCHEMA nightpoint "
               "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO np_runtime")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE np_migrator IN SCHEMA nightpoint "
               "GRANT USAGE, SELECT ON SEQUENCES TO np_runtime")
    op.execute("GRANT USAGE ON SCHEMA migration TO np_runtime")
    op.execute("GRANT SELECT ON migration.alembic_version TO np_runtime")


def downgrade() -> None:
    require_disposable(op.get_bind())
    # Deliberately no CASCADE: refuse to destroy later data or business objects.
    op.execute("DROP SCHEMA nightpoint")
    op.execute("REVOKE SELECT ON migration.alembic_version FROM np_runtime")
    op.execute("REVOKE USAGE ON SCHEMA migration FROM np_runtime")
