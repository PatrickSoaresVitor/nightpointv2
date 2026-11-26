"""Events owns categories, event data and idempotent creation receipts."""
from alembic import op
from app.platform.test_guard import require_disposable
revision = "0005_events"
down_revision = "0004_profile_text"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA events AUTHORIZATION np_migrator")
    op.execute("REVOKE ALL ON SCHEMA events FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA events TO np_runtime")
    op.execute("CREATE TABLE events.event_categories(code text PRIMARY KEY,label text NOT NULL)")
    op.execute("INSERT INTO events.event_categories VALUES('street','Street'),('jdm','JDM'),('premium','Premium'),('drift','Drift')")
    op.execute("""CREATE TABLE events.events(id uuid PRIMARY KEY,
        organizer_id uuid NOT NULL REFERENCES accounts.users(id) ON DELETE RESTRICT,
        category_code text NOT NULL REFERENCES events.event_categories(code) ON DELETE RESTRICT,
        title text NOT NULL CHECK(length(btrim(title)) BETWEEN 1 AND 120 AND length(title)<=120),
        description text CHECK(description IS NULL OR length(description) BETWEEN 1 AND 2000),
        location_label text NOT NULL CHECK(length(btrim(location_label)) BETWEEN 1 AND 200 AND length(location_label)<=200),
        location public.geography(Point,4326) NOT NULL,
        starts_at timestamptz NOT NULL,timezone text NOT NULL CHECK(length(timezone) BETWEEN 1 AND 64),
        state text NOT NULL DEFAULT 'published' CHECK(state IN ('draft','published','cancelled','archived')),
        visibility text NOT NULL DEFAULT 'listed' CHECK(visibility IN ('listed','unlisted')),
        version bigint NOT NULL DEFAULT 1 CHECK(version>0),created_at timestamptz NOT NULL DEFAULT now(),
        CHECK(public.ST_X(location::public.geometry) BETWEEN -180 AND 180 AND public.ST_Y(location::public.geometry) BETWEEN -90 AND 90))""")
    op.execute("CREATE INDEX events_discovery_gist ON events.events USING gist(location) WHERE state='published' AND visibility='listed'")
    op.execute("CREATE INDEX events_start_id_idx ON events.events(starts_at,id)")
    op.execute("CREATE INDEX events_category_start_idx ON events.events(category_code,starts_at,id)")
    op.execute("CREATE INDEX events_organizer_idx ON events.events(organizer_id)")
    op.execute("""CREATE TABLE events.creation_requests(actor_id uuid NOT NULL REFERENCES accounts.users(id) ON DELETE RESTRICT,
        operation text NOT NULL CHECK(operation='events.create.v1'),key uuid NOT NULL,
        fingerprint text NOT NULL CHECK(fingerprint ~ '^[0-9a-f]{64}$'),
        event_id uuid NOT NULL REFERENCES events.events(id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(actor_id,operation,key))""")
    for table in ('event_categories','events','creation_requests'):
        op.execute(f"REVOKE ALL ON events.{table} FROM PUBLIC,np_runtime")
        op.execute(f"GRANT SELECT ON events.{table} TO np_runtime")
    op.execute("GRANT INSERT(id,organizer_id,category_code,title,description,location_label,location,starts_at,timezone) ON events.events TO np_runtime")
    op.execute("GRANT INSERT(actor_id,operation,key,fingerprint,event_id) ON events.creation_requests TO np_runtime")


def downgrade() -> None:
    require_disposable(op.get_bind())
    op.execute("DROP TABLE events.creation_requests")
    op.execute("DROP TABLE events.events")
    op.execute("DROP TABLE events.event_categories")
    op.execute("DROP SCHEMA events")
