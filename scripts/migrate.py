"""Run every database migration, in order, against the configured database (docs/adr/0003).

1. ``app`` schema  -- Alembic (``migrations/app``)
2. ``sirdb`` schema -- the SQL migrations 0001.. (``migrations/sirdb``), same database

Run once per deploy, before new application processes start:

    python scripts/migrate.py            # apply everything pending
    python scripts/migrate.py --status   # show the current app revision and pending sirdb files

Under ``APP_ENV=dev-sqlite`` there is no sirdb and the app tables are created directly.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _plain(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def run(database_url: Optional[str] = None, status_only: bool = False) -> dict[str, object]:
    from alembic import command
    from alembic.config import Config

    from tools.core.config import SETTINGS
    from tools.sirdb import migrate as sirdb_migrate

    url = database_url or SETTINGS.database_url
    if url.startswith("sqlite"):
        from tools.core.db import create_schema, make_engine

        if not status_only:
            create_schema(make_engine(url))
        return {"app": "created (dev-sqlite)", "sirdb": "skipped (dev-sqlite)"}

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = url
    if status_only:
        command.current(cfg)
    else:
        command.upgrade(cfg, "head")
    applied = sirdb_migrate.migrate(_plain(url), status_only=status_only)
    return {"app": "head" if not status_only else "see above", "sirdb": applied}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true", help="report only; change nothing")
    args = parser.parse_args(argv)
    result = run(status_only=args.status)
    print(f"app: {result['app']}")
    print(f"sirdb: {result['sirdb']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
