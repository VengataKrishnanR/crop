"""Compare the two reference sources (legacy ingestion vs sirdb) field by field (docs/adr/0003).

    python scripts/reference_parity.py --load          # migrate, load both from ../Reference, compare
    python scripts/reference_parity.py                 # compare what is already loaded
    python scripts/reference_parity.py --country BG    # one country

Uses CCRE_DATABASE_URL (PostgreSQL, app + sirdb schemas in one database) unless
--database-url is given. Exit code 1 when there are unaccepted differences.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_both(url: str, reference_dir: Path) -> None:
    from sqlalchemy.orm import Session

    from scripts.migrate import run as migrate
    from tools.core.db import make_engine
    from tools.ingestion import ingest_package, ingest_workbook
    from tools.sirdb import loader

    workbook = sorted(reference_dir.glob("M2c*.xlsx"))[0]
    package = sorted(reference_dir.glob("sir-configuration*"))[0]
    migrate(url)
    loader.load(workbook, url.replace("postgresql+psycopg://", "postgresql://"), actor="parity")
    with Session(make_engine(url)) as session:
        ingest_package(session, package)
        ingest_workbook(session, workbook)
        session.commit()


def report(url: str, country: Optional[str] = None):  # noqa: ANN201 -- ParityReport
    from sqlalchemy.orm import Session

    from tools.core.config import sqlalchemy_url
    from tools.core.db import make_engine
    from tools.reference import LegacyReferenceRepository, SirdbReferenceRepository
    from tools.reference.parity import compare

    engine = make_engine(sqlalchemy_url(url))
    with Session(engine) as session:
        return compare(LegacyReferenceRepository(session), SirdbReferenceRepository(engine), country)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url")
    parser.add_argument("--load", action="store_true", help="migrate and load both sources first")
    parser.add_argument("--country")
    args = parser.parse_args(argv)

    from tools.core.config import SETTINGS, sqlalchemy_url

    url = sqlalchemy_url(args.database_url) if args.database_url else SETTINGS.database_url
    if args.load:
        load_both(url, SETTINGS.reference_dir)
    rep = report(url, args.country)
    print(f"counts (legacy, sirdb): {rep.counts}")
    print(f"accepted differences: {rep.accepted}")
    print(f"differences: {len(rep.differences)}")
    for d in rep.differences:
        print("  " + d.line())
    return 0 if rep.clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
