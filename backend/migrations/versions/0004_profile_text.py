"""Freeze a locale-independent text policy; historical 0003 remains unchanged."""
from alembic import op
from app.platform.test_guard import require_disposable

revision = "0004_profile_text"
down_revision = "0003_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""CREATE FUNCTION accounts.valid_profile_text(value text, maximum integer)
        RETURNS boolean LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE SET search_path=pg_catalog AS $$
        SELECT length(value) BETWEEN 1 AND maximum
        AND translate(value,U&'\0020\00a0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200a\2028\2029\202f\205f\3000','') <> ''
        AND NOT EXISTS (SELECT 1 FROM generate_series(1,length(value)) AS p
            WHERE ascii(substr(value,p,1)) BETWEEN 0 AND 31 OR ascii(substr(value,p,1)) BETWEEN 127 AND 159)
        $$""")
    op.execute("REVOKE ALL ON FUNCTION accounts.valid_profile_text(text,integer) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION accounts.valid_profile_text(text,integer) TO np_runtime")
    for field, maximum in (("nickname",80),("avatar_style",64),("avatar_seed",256)):
        op.execute(f"ALTER TABLE accounts.profiles DROP CONSTRAINT profiles_{field}_check")
        op.execute(f"ALTER TABLE accounts.profiles ADD CONSTRAINT profiles_{field}_text_v1 "
                   f"CHECK (accounts.valid_profile_text({field},{maximum}))")


def downgrade() -> None:
    require_disposable(op.get_bind())
    for field, maximum in (("nickname",80),("avatar_style",64),("avatar_seed",256)):
        op.execute(f"ALTER TABLE accounts.profiles DROP CONSTRAINT profiles_{field}_text_v1")
        op.execute(f"ALTER TABLE accounts.profiles ADD CONSTRAINT profiles_{field}_check CHECK "
                   f"(length(btrim({field})) BETWEEN 1 AND {maximum} AND length({field})<={maximum} "
                   f"AND {field} !~ '[[:cntrl:]]')")
    op.execute("DROP FUNCTION accounts.valid_profile_text(text,integer)")
