"""PostgreSQL for the test suite (``make test-pg``; docs/adr/0003).

Preferred: a throw-away PostgreSQL 16 container via Testcontainers. Fallback: an
existing server named by ``CCRE_TEST_PG_URL`` (e.g. the local ``ccre-sirdb``
container on port 55432) -- a fresh database is created there per run and dropped
afterwards, so no loaded data is touched. Credentials are never printed.
"""
from __future__ import annotations

import atexit
import os
import uuid
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

_container = None


def _with_database(url: str, name: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, f"/{name}", p.query, p.fragment))


def _plain(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")


def _server_url() -> str:
    """URL of a server we may create databases on."""
    global _container
    explicit = os.environ.get("CCRE_TEST_PG_URL")
    if explicit:
        return _plain(explicit)
    from testcontainers.postgres import PostgresContainer

    _container = PostgresContainer("postgres:16.4", driver=None)
    _container.start()
    atexit.register(_container.stop)
    return _plain(_container.get_connection_url())


_server: Optional[str] = None


def server_url() -> str:
    global _server
    if _server is None:
        _server = _server_url()
    return _server


def start_test_database() -> str:
    """The run's shared database (empty at start), created once per process.

    conftest is imported both as ``conftest`` and as ``tests.conftest``; both must
    use the same database.
    """
    if not os.environ.get("CCRE_TEST_PG_DB"):
        os.environ["CCRE_TEST_PG_DB"] = create_database()
    return os.environ["CCRE_TEST_PG_DB"]


def create_database(prefix: str = "ccre_test") -> str:
    """A new, empty database on the test server, dropped at exit. Returns its URL."""
    import psycopg

    server = server_url()
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(server, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')

    def _drop() -> None:
        try:
            with psycopg.connect(server, autocommit=True) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        except Exception:  # noqa: BLE001 -- best effort at interpreter exit
            pass

    if _container is None:
        atexit.register(_drop)
    return _with_database(server, name)
