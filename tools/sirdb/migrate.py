"""Apply the versioned SQL migrations in ``migrations/sirdb`` (Phase 2).

Each file ``NNNN_name.sql`` runs once, in order, inside its own transaction, and is
recorded in ``sirdb.schema_migration`` with its SHA-256. A recorded migration whose
file has since changed is refused — fix forward with a new migration instead.

Run:  python -m tools.sirdb.migrate            (apply pending)
      python -m tools.sirdb.migrate --status   (list applied / pending)
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Optional

from .db import ROOT, connect, database_url, redacted

MIGRATIONS = ROOT / "migrations" / "sirdb"

_BOOTSTRAP = """
CREATE SCHEMA IF NOT EXISTS sirdb;
CREATE TABLE IF NOT EXISTS sirdb.schema_migration (
    version     text PRIMARY KEY,
    filename    text NOT NULL,
    sha256      char(64) NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
"""


def migration_files() -> list[Path]:
    return sorted(p for p in MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def migrate(url: Optional[str] = None, status_only: bool = False) -> list[str]:
    applied_now: list[str] = []
    with connect(url, actor="migrator") as conn:
        with conn.cursor() as cur:
            cur.execute(_BOOTSTRAP)
            conn.commit()
            cur.execute("SELECT version, sha256 FROM sirdb.schema_migration")
            done = dict(cur.fetchall())
        for path in migration_files():
            version = path.name.split("_", 1)[0]
            sha = _sha(path)
            if version in done:
                if done[version] != sha:
                    raise RuntimeError(f"Migration {path.name} changed after it was applied "
                                       "(checksum differs). Add a new migration instead.")
                continue
            if status_only:
                applied_now.append(f"pending {path.name}")
                continue
            with conn.cursor() as cur:
                cur.execute(path.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO sirdb.schema_migration (version, filename, sha256) VALUES (%s, %s, %s)",
                            (version, path.name, sha))
            conn.commit()
            applied_now.append(path.name)
    return applied_now


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Apply SIR/SIRG database migrations.")
    ap.add_argument("--url", help="database URL (default: SIRDB_DATABASE_URL)")
    ap.add_argument("--status", action="store_true")
    args = ap.parse_args(argv)
    print(f"database: {redacted(database_url(args.url))}")
    done = migrate(args.url, status_only=args.status)
    print("\n".join(done) if done else "up to date")


if __name__ == "__main__":
    main()
