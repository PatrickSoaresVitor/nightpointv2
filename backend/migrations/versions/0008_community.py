"""Event-scoped interactions; no public profile or irreversible deletion."""
from alembic import op
from app.platform.test_guard import require_disposable

revision = '0008_community'
down_revision = '0007_garage'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA community AUTHORIZATION np_migrator')
    op.execute('REVOKE ALL ON SCHEMA community FROM PUBLIC')
    op.execute('GRANT USAGE ON SCHEMA community TO np_runtime')
    op.execute('''CREATE TABLE community.reactions(
        event_id uuid NOT NULL REFERENCES events.events(id) ON DELETE RESTRICT,
        actor_id uuid NOT NULL REFERENCES accounts.users(id) ON DELETE RESTRICT,
        kind text NOT NULL CHECK(kind IN ('like','participation')),active boolean NOT NULL,
        updated_at timestamptz NOT NULL DEFAULT now(),PRIMARY KEY(event_id,actor_id,kind))''')
    op.execute('''CREATE TABLE community.comments(
        id uuid PRIMARY KEY,event_id uuid NOT NULL REFERENCES events.events(id) ON DELETE RESTRICT,
        actor_id uuid NOT NULL REFERENCES accounts.users(id) ON DELETE RESTRICT,
        text text NOT NULL CHECK(length(btrim(text)) BETWEEN 1 AND 1000 AND length(text)<=1000),
        version bigint NOT NULL DEFAULT 1 CHECK(version>0),removed boolean NOT NULL DEFAULT false,
        removed_by uuid REFERENCES accounts.users(id) ON DELETE RESTRICT,
        created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now(),
        CHECK(removed=(removed_by IS NOT NULL)))''')
    op.execute('CREATE INDEX community_comments_page ON community.comments(event_id,created_at DESC,id DESC)')
    op.execute('''CREATE TABLE community.creation_requests(
        event_id uuid NOT NULL REFERENCES events.events(id) ON DELETE RESTRICT,
        actor_id uuid NOT NULL REFERENCES accounts.users(id) ON DELETE RESTRICT,key uuid NOT NULL,
        fingerprint text NOT NULL CHECK(fingerprint ~ '^[0-9a-f]{64}$'),
        comment_id uuid NOT NULL REFERENCES community.comments(id) ON DELETE RESTRICT,PRIMARY KEY(event_id,actor_id,key))''')
    for table in ('reactions','comments','creation_requests'):
        op.execute(f'REVOKE ALL ON community.{table} FROM PUBLIC,np_runtime')
        op.execute(f'GRANT SELECT ON community.{table} TO np_runtime')
    op.execute('GRANT INSERT(event_id,actor_id,kind,active), UPDATE(active,updated_at) ON community.reactions TO np_runtime')
    op.execute('GRANT INSERT(id,event_id,actor_id,text), UPDATE(removed,removed_by,version,updated_at) ON community.comments TO np_runtime')
    op.execute('GRANT INSERT(event_id,actor_id,key,fingerprint,comment_id) ON community.creation_requests TO np_runtime')


def downgrade() -> None:
    require_disposable(op.get_bind())
    for table in ('creation_requests','comments','reactions'): op.execute(f'DROP TABLE community.{table}')
    op.execute('DROP SCHEMA community')
