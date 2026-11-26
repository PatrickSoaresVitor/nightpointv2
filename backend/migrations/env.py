from alembic import context
from sqlalchemy import create_engine

from app.platform.config import load_settings
from app.platform.test_guard import protect_engine, UnsafeTestTarget

settings = load_settings()
if settings.db_user != "np_migrator":
    raise ValueError("Migrations require the migrator role")

command = getattr(getattr(context.config, "cmd_opts", None), "cmd", None)
command_name = getattr(command[0], "__name__", "") if command else ""
if settings.environment != "test" and command_name != "upgrade":
    raise UnsafeTestTarget("Only explicit local upgrades are allowed without disposable attestation")

if context.is_offline_mode():
    raise UnsafeTestTarget("Offline execution cannot prove the target identity")
else:
    engine = create_engine(settings.database_url(), hide_parameters=True,
                           connect_args={"connect_timeout": 3})
    try:
        if settings.environment == "test":
            protect_engine(engine)
        with engine.connect() as connection:
            context.configure(connection=connection, version_table_schema="migration")
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
