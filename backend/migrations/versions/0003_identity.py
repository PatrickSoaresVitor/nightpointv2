"""Identity owns all accounts tables. Explicit object and column grants."""
from alembic import op
from app.platform.test_guard import require_disposable

revision = "0003_identity"
down_revision = "0002_privileges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA accounts AUTHORIZATION np_migrator")
    op.execute("REVOKE ALL ON SCHEMA accounts FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA accounts TO np_runtime")
    op.execute("CREATE TABLE accounts.users (id uuid PRIMARY KEY, "
               "state text NOT NULL DEFAULT 'active' CHECK (state IN ('active')), "
               "created_at timestamptz NOT NULL DEFAULT now())")
    op.execute("CREATE TABLE accounts.identity_links (issuer text NOT NULL "
               "CHECK (length(issuer) BETWEEN 1 AND 256 AND issuer !~ '[[:cntrl:]]'), "
               "subject text NOT NULL CHECK (length(subject) BETWEEN 1 AND 128 AND subject !~ '[[:cntrl:]]'), "
               "user_id uuid NOT NULL REFERENCES accounts.users(id), "
               "linked_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(issuer,subject))")
    op.execute("CREATE INDEX identity_links_user_idx ON accounts.identity_links(user_id)")
    op.execute("CREATE TABLE accounts.profiles (user_id uuid PRIMARY KEY REFERENCES accounts.users(id), "
               "nickname text NOT NULL CHECK (length(btrim(nickname)) BETWEEN 1 AND 80 "
               "AND length(nickname)<=80 AND nickname !~ '[[:cntrl:]]'), "
               "avatar_style text CHECK (avatar_style IS NULL OR (length(btrim(avatar_style)) BETWEEN 1 AND 64 "
               "AND length(avatar_style)<=64 AND avatar_style !~ '[[:cntrl:]]')), "
               "avatar_seed text CHECK (avatar_seed IS NULL OR (length(btrim(avatar_seed)) BETWEEN 1 AND 256 "
               "AND length(avatar_seed)<=256 AND avatar_seed !~ '[[:cntrl:]]')), "
               "version integer NOT NULL DEFAULT 1 CHECK(version>0), "
               "updated_at timestamptz NOT NULL DEFAULT now())")
    for table in ("users", "identity_links", "profiles"):
        op.execute(f"REVOKE ALL ON accounts.{table} FROM PUBLIC, np_runtime")
        op.execute(f"GRANT SELECT ON accounts.{table} TO np_runtime")
    op.execute("GRANT INSERT(id) ON accounts.users TO np_runtime")
    op.execute("GRANT INSERT(issuer,subject,user_id) ON accounts.identity_links TO np_runtime")
    op.execute("GRANT INSERT(user_id,nickname,avatar_style,avatar_seed), "
               "UPDATE(nickname,avatar_style,avatar_seed,version,updated_at) ON accounts.profiles TO np_runtime")


def downgrade() -> None:
    require_disposable(op.get_bind())
    op.execute("DROP TABLE accounts.profiles")
    op.execute("DROP TABLE accounts.identity_links")
    op.execute("DROP TABLE accounts.users")
    op.execute("DROP SCHEMA accounts")
