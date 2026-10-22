"""Engine and session handling.

The application tables live in the PostgreSQL schema ``app`` (``sirdb`` sits beside
it in the same database; docs/adr/0003). SQLite has no schemas, so SQLite engines
map ``app`` to the default schema; every engine is built by :func:`make_engine`.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import SETTINGS
from .models import APP_SCHEMA, Base


def make_engine(url: str, **kwargs: Any) -> Engine:
    """An engine for the app tables. SQLite: no schema, cross-thread connections allowed."""
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, **kwargs.pop("connect_args", {})}
        eng = create_engine(url, connect_args=connect_args, **kwargs)
        return eng.execution_options(schema_translate_map={APP_SCHEMA: None})
    kwargs.setdefault("pool_pre_ping", True)
    return create_engine(url, **kwargs)


def create_schema(eng: Engine) -> None:
    """Create the app tables directly (dev-sqlite and tests). Other environments migrate."""
    if eng.dialect.name == "postgresql":
        with eng.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {APP_SCHEMA}"))
    Base.metadata.create_all(eng)


engine = make_engine(SETTINGS.database_url, echo=SETTINGS.echo_sql)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    """Make sure the app tables exist.

    dev-sqlite and test create them in place; on any other environment the schema
    is owned by migrations (``python scripts/migrate.py``), so this only creates
    what a fresh developer database lacks and never alters existing tables.
    """
    create_schema(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
