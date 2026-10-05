import asyncio
import os
import sys
from logging.config import fileConfig

from alembic.autogenerate import comparators
from alembic.util import CommandError
from sqlalchemy import Enum
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Add your app directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'app')))

from app import models  # Import models so Alembic sees them  # noqa: F401
from app.core.config import settings
from app.core.db import Base

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set SQLAlchemy URL from your settings
config.set_main_option(
    "sqlalchemy.url",
    f"postgresql+asyncpg://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
)

target_metadata = Base.metadata


@comparators.dispatch_for("schema")
def compare_enum_labels(autogen_context, upgrade_ops, schemas):
    """Fails while a native enum's labels differ from its Python enum's, which stock
    autogenerate never compares. It raises rather than emitting an op, and compares
    label sets rather than their order — rules/database.md (native enums) says why."""
    db = {e["name"]: set(e["labels"]) for e in autogen_context.inspector.get_enums()}
    declared = {
        col.type.name: set(col.type.enums)
        for table in autogen_context.metadata.tables.values()
        for col in table.columns
        if isinstance(col.type, Enum) and col.type.native_enum
    }
    # A type the DB lacks is a new column's, which stock autogenerate already emits.
    drift = {name: (db[name], labels) for name, labels in declared.items() if name in db and db[name] != labels}
    if drift:
        raise CommandError(f"Enum labels differ (database, models): {drift}")


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()

async def run_migrations_online():
    """Run migrations in 'online' mode with async engine."""
    connectable = create_async_engine(
        config.get_main_option("sqlalchemy.url"),
        pool_pre_ping=True,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
