"""Shared fixtures.

Tests run against a fresh in-memory database. The ``real_*`` fixtures use the
actual artifacts in ``../Reference/`` and skip cleanly when they are absent, so the
suite stays runnable on a machine without them.

The suite always runs offline: the stub LLM is forced, and the agents' own
database tools point at a throwaway SQLite file, never the developer's data.
"""
from __future__ import annotations

import datetime as dt
import os
import tempfile
from pathlib import Path
from typing import Optional

# Must be set before any app module reads its settings.
os.environ["CCRE_LLM_MODE"] = "stub"
os.environ["CCRE_AGENTS_ENABLED"] = "1"
os.environ["AUTH_MODE"] = "none"
os.environ["LOG_LEVEL"] = "WARNING"
# Two modes (docs/adr/0003): plain `pytest` runs on SQLite with the legacy reference
# source; `make test-pg` sets CCRE_TEST_PG=1 and runs the same suite on PostgreSQL.
TEST_PG = os.environ.get("CCRE_TEST_PG") == "1"
if TEST_PG:
    from tests.pg import start_test_database  # noqa: E402

    os.environ["APP_ENV"] = "test"
    os.environ["CCRE_DATABASE_URL"] = start_test_database()
else:
    os.environ["APP_ENV"] = "dev-sqlite"
    os.environ["CCRE_DATABASE_URL"] = "sqlite:///" + (
        Path(tempfile.mkdtemp(prefix="ccre_test_")) / "agent_tools.db"
    ).as_posix()
os.environ["REFERENCE_SOURCE"] = "legacy"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from tools.core.models import (
    Base, ConfigPackage, CtryProcMapping, OnboardingCase, PermittedValue, Rule, RuleBinding,
    RuleSet, SirAttribute, SirDef, SirgDef,
)

# CCRE_REFERENCE_DIR points the tests at copies (e.g. while the workbook is open in Excel, which locks it).
REFERENCE = Path(os.environ["CCRE_REFERENCE_DIR"]) if os.environ.get("CCRE_REFERENCE_DIR") else Path(__file__).resolve().parents[2] / "Reference"


def _fresh_engine():
    """An empty app database for one test.

    SQLite: a private in-memory database. PostgreSQL: the run's shared database,
    every app table truncated, so each test still starts empty.
    """
    from tools.core.db import create_schema, make_engine

    if not TEST_PG:
        engine = make_engine("sqlite://", poolclass=StaticPool)
        create_schema(engine)
        return engine, True
    from tools.core.db import engine
    # DELETE, not TRUNCATE: TRUNCATE needs an exclusive lock and waits forever behind any
    # session a previous test left idle in a transaction.
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("SET LOCAL lock_timeout = '10s'"))
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    return engine, False


@pytest.fixture
def session() -> Session:
    engine, private = _fresh_engine()
    maker = sessionmaker(bind=engine, expire_on_commit=False)
    db = maker()
    try:
        yield db
    finally:
        db.close()
        if private:
            engine.dispose()


def _package_path() -> Optional[Path]:
    matches = sorted(REFERENCE.glob("sir-configuration*"))
    return matches[0] if matches else None


def _workbook_path() -> Optional[Path]:
    matches = sorted(REFERENCE.glob("M2c*.xlsx"))
    return matches[0] if matches else None


@pytest.fixture
def real_package_path() -> Path:
    path = _package_path()
    if path is None:
        pytest.skip("no sir-configuration package in Reference/")
    return path


@pytest.fixture
def real_workbook_path() -> Path:
    path = _workbook_path()
    if path is None:
        pytest.skip("no M2C workbook in Reference/")
    return path


@pytest.fixture
def ingested(session: Session, real_package_path: Path, real_workbook_path: Path) -> dict:
    """Both real artifacts loaded. The integration baseline."""
    from tools.ingestion import ingest_package, ingest_workbook

    pkg = ingest_package(session, real_package_path)
    wb = ingest_workbook(session, real_workbook_path)
    session.commit()
    return {"package": pkg, "workbook": wb, "rule_set_id": wb.rule_set_id}


# --------------------------------------------------------------------------- #
# Hand-built fixtures, for checks that need an exact shape
# --------------------------------------------------------------------------- #

@pytest.fixture
def tiny_catalog(session: Session) -> dict[str, str]:
    """A two-group, two-definition catalog with one attribute each."""
    session.add_all([
        ConfigPackage(version="t1", source_name="tiny-test-package"),
        SirgDef(id="sirg-ioss", cd="IOSS", nm="Import One-Stop Shop", package_version="t1"),
        SirgDef(id="sirg-poab", cd="POAB", nm="Power of Attorney", package_version="t1"),
        SirDef(id="sir-ioss-bg", package_version="t1", nm="IOSS - BG", cmpt_nm="IOSSBG", ctry_cd="BG"),
        SirDef(id="sir-poab-bg", package_version="t1", nm="POAB - BG", cmpt_nm="POABBG", ctry_cd="BG"),
        SirAttribute(
            att_id="att-ioss-1", sir_id="sir-ioss-bg", package_version="t1",
            ent_path="/Shipment", nm="IOSS number",
        ),
        SirAttribute(
            att_id="att-poab-1", sir_id="sir-poab-bg", package_version="t1",
            ent_path="/Shipment", nm="POA upload",
        ),
        CtryProcMapping(
            ctry_cd="BG", proc_lvl_cd="IMP_CLR", sirg_id="sirg-ioss",
            sir_id="sir-ioss-bg", package_version="t1",
        ),
        CtryProcMapping(
            ctry_cd="BG", proc_lvl_cd="IMP_CLR", sirg_id="sirg-poab",
            sir_id="sir-poab-bg", package_version="t1",
        ),
    ])
    for value in ("EUR", "BGN", "USD"):
        session.add(PermittedValue(field="currency", value=value, source_version="w1"))
    session.add(PermittedValue(field="shipment_type", value="B2C", source_version="w1"))
    session.commit()
    return {"package_version": "t1", "workbook_version": "w1"}


@pytest.fixture
def bg_case(session: Session) -> OnboardingCase:
    case = OnboardingCase(
        code="ONB-2026-BG-014",
        ctry_cd="BG",
        title="BG B2C automated contact trigger",
        gccp_ref="Wave 25 ph 1",
        requested_rtp=dt.date(2026, 11, 1),
        state="DRAFT",
    )
    session.add(case)
    session.commit()
    return case


def make_rule_set(
    session: Session,
    case_id: Optional[str] = None,
    version: str = "v0.1",
    workbook_version: str = "w1",
) -> RuleSet:
    rule_set = RuleSet(case_id=case_id, version=version, source_version=workbook_version)
    session.add(rule_set)
    session.commit()
    return rule_set


def add_rule(
    session: Session,
    rule_set_id: str,
    ctry_cd: str = "BG",
    sirg_cd: str = "IOSS",
    other_logic: Optional[str] = '!serviceCodeList.contains("DD")',
    sir_id: Optional[str] = "sir-ioss-bg",
    currency: str = "BGN",
    doc_reference: Optional[str] = None,
    bind: bool = True,
    **kwargs,
) -> Rule:
    rule = Rule(
        rule_set_id=rule_set_id,
        ctry_cd=ctry_cd,
        sirg_cd=sirg_cd,
        other_logic=other_logic,
        shipment_type=kwargs.pop("shipment_type", "B2C"),
        currency=currency,
        value_basis=kwargs.pop("value_basis", "DV"),
        row_no=kwargs.pop("row_no", 1),
        **kwargs,
    )
    rule.doc_reference = doc_reference if doc_reference is not None else rule.generated_doc_reference
    session.add(rule)
    session.flush()
    if bind:
        session.add(RuleBinding(
            rule_id=rule.id, sirg_cd=sirg_cd, sirg_id=f"sirg-{sirg_cd.lower()}",
            sir_id=sir_id, cmpt_nm=f"{sirg_cd}BG", attribute_ids=[],
        ))
    session.commit()
    return rule


# --------------------------------------------------------------------------- #
# HTTP client over an in-memory database
# --------------------------------------------------------------------------- #

@pytest.fixture
def client():
    """FastAPI TestClient whose request sessions use a fresh in-memory database."""
    from fastapi.testclient import TestClient

    from server.app import app
    from tools.core.db import get_session

    engine, private = _fresh_engine()
    maker = sessionmaker(bind=engine, expire_on_commit=False)

    def override():
        db = maker()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    if private:
        engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _agent_tool_schema() -> None:
    """The agents' FunctionTools use the global engine (the throwaway file above)."""
    from tools.core.db import init_db

    init_db()


#: A complete set of M2C criteria for requirement intake (the submit gate needs every column).
FULL_M2C = {
    "region": "EU", "shipment_type": "B2C", "effective_date": "15-11-2026", "expiry_date": "N/A",
    "network_product_codes": "N/A", "min_value": "N/A", "max_value": "N/A",
    "min_weight": "N/A", "max_weight": "N/A", "other_logic": "N/A",
}
