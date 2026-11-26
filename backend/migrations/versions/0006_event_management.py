"""Owner-only events and reversible, versioned management; no physical removal."""
from alembic import op
from app.platform.test_guard import require_disposable

revision = "0006_event_management"
down_revision = "0005_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE events.events ADD COLUMN updated_at timestamptz")
    op.execute("UPDATE events.events SET updated_at=created_at")
    op.execute("ALTER TABLE events.events ALTER COLUMN updated_at SET DEFAULT now(), ALTER COLUMN updated_at SET NOT NULL")
    op.execute("ALTER TABLE events.events DROP CONSTRAINT events_visibility_check")
    op.execute("ALTER TABLE events.events ADD CONSTRAINT events_visibility_check CHECK(visibility IN ('listed','unlisted','owner_only'))")
    op.execute("GRANT INSERT(visibility), UPDATE(title,category_code,starts_at,timezone,location_label,location,description,visibility,state,version,updated_at) ON events.events TO np_runtime")


def downgrade() -> None:
    require_disposable(op.get_bind())
    # A private event cannot silently become public during a downgrade.
    op.execute("UPDATE events.events SET visibility='unlisted' WHERE visibility='owner_only'")
    op.execute("REVOKE UPDATE ON events.events FROM np_runtime")
    for column in ('title','category_code','starts_at','timezone','location_label','location','description','visibility','state','version','updated_at'):
        op.execute(f"REVOKE UPDATE({column}) ON events.events FROM np_runtime")
    op.execute("REVOKE INSERT(visibility) ON events.events FROM np_runtime")
    op.execute("ALTER TABLE events.events DROP COLUMN updated_at")
    op.execute("ALTER TABLE events.events DROP CONSTRAINT events_visibility_check")
    op.execute("ALTER TABLE events.events ADD CONSTRAINT events_visibility_check CHECK(visibility IN ('listed','unlisted'))")
