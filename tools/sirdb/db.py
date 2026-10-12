"""Connection to the SIR/SIRG PostgreSQL database.

The URL comes from the environment variable ``SIRDB_DATABASE_URL``; if it is not set,
``deploy/sirdb.env`` (git-ignored) is read. Credentials are never hard-coded or logged.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import psycopg

ROOT = Path(__file__).resolve().parents[2]


def database_url(explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    url = os.environ.get("SIRDB_DATABASE_URL")
    if url:
        return url
    env_file = ROOT / "deploy" / "sirdb.env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("SIRDB_DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("Set SIRDB_DATABASE_URL (see deploy/sirdb.env.example).")


def redacted(url: str) -> str:
    """The URL with the password hidden, for messages."""
    from urllib.parse import urlsplit, urlunsplit
    p = urlsplit(url)
    if p.password:
        netloc = p.netloc.replace(f":{p.password}@", ":***@")
        return urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))
    return url


def connect(url: Optional[str] = None, actor: str = "sirdb") -> psycopg.Connection:
    conn = psycopg.connect(database_url(url), autocommit=False)
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('sirdb.actor', %s, false)", (actor,))
    conn.commit()
    return conn
