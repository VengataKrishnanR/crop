"""Alembic environment for the ``app`` schema.

Only tables in schema ``app`` are managed here; ``sirdb`` has its own SQL migrations
(``migrations/sirdb``), run by the same ``scripts/migrate.py`` step.
"""
from __future__ import annotations

from alembic import context
from sqlalchemy import text

from tools.core.config import SETTINGS
from tools.core.db import make_engine
from tools.core.models import APP_SCHEMA, Base

config = context.config
target_metadata = Base.metadata


def _include_name(name, type_, parent_names):  # noqa: ANN001 -- alembic callback signature
    if type_ == "schema":
        return name == APP_SCHEMA
    return True


def run_migrations_online() -> None:
    url = config.attributes.get("database_url") or SETTINGS.database_url
    engine = make_engine(url)
    is_pg = engine.dialect.name == "postgresql"
    with engine.connect() as connection:
        if is_pg:
            connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {APP_SCHEMA}"))
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=is_pg,
            include_name=_include_name,
            version_table_schema=APP_SCHEMA if is_pg else None,
            render_as_batch=not is_pg,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) mode is not supported; run against a database.")
run_migrations_online()
