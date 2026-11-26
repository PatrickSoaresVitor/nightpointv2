"""Private multi-vehicle garage with reversible archive and append-only revisions."""
from alembic import op
from app.platform.test_guard import require_disposable

revision = '0007_garage'
down_revision = '0006_event_management'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE SCHEMA garage AUTHORIZATION np_migrator')
    op.execute('REVOKE ALL ON SCHEMA garage FROM PUBLIC')
    op.execute('GRANT USAGE ON SCHEMA garage TO np_runtime')
    op.execute('''CREATE TABLE garage.vehicles(
        id uuid PRIMARY KEY,owner_id uuid NOT NULL REFERENCES accounts.users(id) ON DELETE RESTRICT,
        brand text NOT NULL CHECK(length(btrim(brand)) BETWEEN 1 AND 80 AND length(brand)<=80),
        model text NOT NULL CHECK(length(btrim(model)) BETWEEN 1 AND 120 AND length(model)<=120),
        year integer CHECK(year BETWEEN 1900 AND 2100),color text CHECK(length(btrim(color)) BETWEEN 1 AND 60 AND length(color)<=60),
        category text NOT NULL CHECK(category IN ('car','motorcycle','truck','other')),
        is_primary boolean NOT NULL DEFAULT false,archived boolean NOT NULL DEFAULT false,
        version bigint NOT NULL DEFAULT 1 CHECK(version>0),created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),CHECK(NOT(archived AND is_primary)))''')
    op.execute('CREATE UNIQUE INDEX garage_one_primary ON garage.vehicles(owner_id) WHERE is_primary AND NOT archived')
    op.execute('CREATE INDEX garage_owner_page ON garage.vehicles(owner_id,archived,created_at DESC,id DESC)')
    op.execute('''CREATE TABLE garage.creation_requests(owner_id uuid NOT NULL REFERENCES accounts.users(id) ON DELETE RESTRICT,
        key uuid NOT NULL,fingerprint text NOT NULL CHECK(fingerprint ~ '^[0-9a-f]{64}$'),
        vehicle_id uuid NOT NULL REFERENCES garage.vehicles(id) ON DELETE RESTRICT,PRIMARY KEY(owner_id,key))''')
    op.execute('''CREATE TABLE garage.vehicle_revisions(vehicle_id uuid NOT NULL REFERENCES garage.vehicles(id) ON DELETE RESTRICT,
        version bigint NOT NULL CHECK(version>0),kind text NOT NULL CHECK(kind IN ('created','updated','archived','primary_replaced')),
        snapshot jsonb NOT NULL CHECK(jsonb_typeof(snapshot)='object'),created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY(vehicle_id,version))''')
    for table in ('vehicles','creation_requests','vehicle_revisions'):
        op.execute(f'REVOKE ALL ON garage.{table} FROM PUBLIC,np_runtime')
        op.execute(f'GRANT SELECT ON garage.{table} TO np_runtime')
    op.execute('GRANT INSERT(id,owner_id,brand,model,year,color,category,is_primary), '
               'UPDATE(brand,model,year,color,category,is_primary,archived,version,updated_at) ON garage.vehicles TO np_runtime')
    op.execute('GRANT INSERT(owner_id,key,fingerprint,vehicle_id) ON garage.creation_requests TO np_runtime')
    op.execute('GRANT INSERT(vehicle_id,version,kind,snapshot) ON garage.vehicle_revisions TO np_runtime')


def downgrade() -> None:
    require_disposable(op.get_bind())
    for table in ('vehicle_revisions','creation_requests','vehicles'): op.execute(f'DROP TABLE garage.{table}')
    op.execute('DROP SCHEMA garage')
