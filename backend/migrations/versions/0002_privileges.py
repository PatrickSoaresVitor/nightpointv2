"""Default deny for future objects; explicit object grants belong to each migration."""
from alembic import op
from app.platform.test_guard import require_disposable

revision = "0002_privileges"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE np_migrator IN SCHEMA nightpoint "
               "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM np_runtime")
    op.execute("ALTER DEFAULT PRIVILEGES FOR ROLE np_migrator IN SCHEMA nightpoint "
               "REVOKE USAGE, SELECT ON SEQUENCES FROM np_runtime")


def downgrade() -> None:
    require_disposable(op.get_bind())
    # Intentionally do not restore broad defaults even on downgrade.
