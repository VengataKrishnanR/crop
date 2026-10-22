"""Database policy (Phase 2, docs/adr/0003): settings, optimistic locking, package pinning,
the reference repository and its boundary, Alembic migrations, and legacy-vs-sirdb parity.

The migration, sirdb-repository and parity tests need PostgreSQL and run under
``make test-pg`` (``CCRE_TEST_PG=1``); the rest run in both modes.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from tests.conftest import REFERENCE, TEST_PG, add_rule, make_rule_set
from tools.core.config import ConfigError, Settings, sqlalchemy_url
from tools.core.models import OnboardingCase, PackageUpload, RuleSet
from tools.reference import LegacyReferenceRepository, get_reference
from tools.reference.parity import compare

ROOT = Path(__file__).resolve().parents[1]
BUSINESS = {"X-CCRE-Role": "BUSINESS"}
needs_pg = pytest.mark.skipif(not TEST_PG, reason="PostgreSQL only: run with make test-pg (CCRE_TEST_PG=1)")


# --------------------------------------------------------------------------- #
# Settings policy
# --------------------------------------------------------------------------- #

def _settings(**env: str) -> Settings:
    return Settings(**{"CCRE_DATABASE_URL": "", "REFERENCE_SOURCE": "", **env})


def test_postgres_is_required_outside_dev_sqlite() -> None:
    with pytest.raises(ConfigError, match="CCRE_DATABASE_URL is required"):
        _settings(APP_ENV="dev")
    s = _settings(APP_ENV="dev", CCRE_DATABASE_URL="postgresql://u:p@db:5432/ccre")
    assert s.database_url == "postgresql+psycopg://u:p@db:5432/ccre"
    assert s.reference_source == "sirdb" and s.sirdb_sqlalchemy_url == s.database_url


def test_sqlite_only_in_dev_sqlite_and_never_in_prod() -> None:
    with pytest.raises(ConfigError, match="refused when APP_ENV=prod"):
        _settings(APP_ENV="prod", CCRE_DATABASE_URL="sqlite:///x.db")
    with pytest.raises(ConfigError, match="only allowed with APP_ENV=dev-sqlite"):
        _settings(APP_ENV="test", CCRE_DATABASE_URL="sqlite:///x.db")
    s = _settings(APP_ENV="dev-sqlite")
    assert s.is_sqlite and s.reference_source == "legacy"
    with pytest.raises(ConfigError, match="needs PostgreSQL"):
        _ = s.sirdb_sqlalchemy_url
    assert _settings(APP_ENV="dev-sqlite", CCRE_SIRDB_URL="postgresql://h/sirdb").sirdb_sqlalchemy_url \
        == "postgresql+psycopg://h/sirdb"
    with pytest.raises(Exception):
        _settings(APP_ENV="staging", CCRE_DATABASE_URL="postgresql://h/db")


def test_explicit_reference_source_wins() -> None:
    assert _settings(APP_ENV="dev", CCRE_DATABASE_URL="postgresql://h/db",
                     REFERENCE_SOURCE="legacy").reference_source == "legacy"
    assert sqlalchemy_url("postgres://h/db") == "postgresql+psycopg://h/db"


# --------------------------------------------------------------------------- #
# Optimistic locking
# --------------------------------------------------------------------------- #

def test_stale_update_of_a_case_raises(session, bg_case) -> None:
    other = sessionmaker(bind=session.get_bind(), expire_on_commit=False)()
    try:
        mine = session.get(OnboardingCase, bg_case.id)
        theirs = other.get(OnboardingCase, bg_case.id)
        assert mine.row_version == theirs.row_version == 1
        theirs.title = "changed by someone else"
        other.commit()
        mine.title = "my edit on a stale view"
        with pytest.raises(StaleDataError):
            session.commit()
    finally:
        session.rollback()
        other.close()


def test_stale_update_of_a_draft_rule_raises(session, tiny_catalog) -> None:
    rs = make_rule_set(session)
    rule = add_rule(session, rs.id)
    other = sessionmaker(bind=session.get_bind(), expire_on_commit=False)()
    try:
        theirs = other.get(type(rule), rule.id)
        theirs.currency = "EUR"
        other.commit()
        rule.currency = "USD"
        with pytest.raises(StaleDataError):
            session.commit()
    finally:
        session.rollback()
        other.close()


def test_transition_with_stale_if_match_is_refused(client) -> None:
    case = client.post("/api/onboardings", json={"ctry_cd": "BG", "title": "BG IOSS"}, headers=BUSINESS).json()
    assert case["row_version"] == 1
    resp = client.post(f"/api/onboardings/{case['id']}/transition", json={"name": "submit_requirement"},
                       headers={**BUSINESS, "If-Match": "99"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "STALE" and resp.json()["detail"]["current_version"] == 1


def test_stale_data_error_is_answered_with_409() -> None:
    from server.app import _stale_write

    resp = _stale_write(None, StaleDataError("stale"))
    assert resp.status_code == 409 and b'"STALE"' in resp.body


# --------------------------------------------------------------------------- #
# Package pin at configuration time
# --------------------------------------------------------------------------- #

def test_m2c_draft_pins_package_version_and_hash(session, tiny_catalog, bg_case) -> None:
    from tools.workflow.case_facts import start_m2c_draft

    rs = make_rule_set(session)
    add_rule(session, rs.id)
    session.add(PackageUpload(filename="sir-configuration-t1.zip", sha256="a" * 64, size=1, stored_path="x",
                              version="t1", status="ACTIVE", uploaded_by="admin",
                              decided_at=dt.datetime(2026, 10, 1)))
    session.commit()
    draft, copied = start_m2c_draft(session, bg_case, "tester")
    assert copied == 1 and draft.source_version == "w1"
    assert (bg_case.package_version, bg_case.package_hash) == ("t1", "a" * 64)


def test_m2c_draft_without_upload_pins_version_only(session, tiny_catalog, bg_case) -> None:
    from tools.workflow.case_facts import start_m2c_draft

    start_m2c_draft(session, bg_case, "tester")
    assert (bg_case.package_version, bg_case.package_hash) == ("t1", None)


# --------------------------------------------------------------------------- #
# Reference repository (legacy) and the TBD hold-code check
# --------------------------------------------------------------------------- #

def test_legacy_repository_reads_the_baseline_not_case_drafts(session, tiny_catalog, bg_case) -> None:
    baseline = make_rule_set(session)
    add_rule(session, baseline.id, row_no=7)
    draft = RuleSet(case_id=bg_case.id, version="v0.1", source_version="w1")
    session.add(draft)
    session.commit()
    add_rule(session, draft.id, row_no=8, currency="USD")
    repo = get_reference(session)
    assert isinstance(repo, LegacyReferenceRepository)
    rows = repo.baseline_rules("BG")
    assert [r.row_no for r in rows] == [7] and rows[0].bindings[0].sir_id == "sir-ioss-bg"
    assert repo.permitted_values()["currency"] == {"EUR", "BGN", "USD"}
    assert repo.workbook_version() == "w1"


def test_get_reference_refuses_unknown_source(session) -> None:
    with pytest.raises(ValueError):
        get_reference(session, source="workbook")


def test_tbd_hold_code_is_a_blocking_row_error(session, tiny_catalog) -> None:
    from tools import ruleconfig as rc

    rs = make_rule_set(session)
    rule = add_rule(session, rs.id, country_hold_cd="TBD", global_hold_cd="CIDM")
    issues = rc.row_issues(rule, rc.Catalog.load(session, "BG"), "BG")
    assert any(i["level"] == "error" and i["field"] == "country_hold_cd" and "TBD" in i["message"] for i in issues)


# --------------------------------------------------------------------------- #
# Boundary: reference reads only through the repository
# --------------------------------------------------------------------------- #

# Writers of the ingestion tables and the ingestion entry points (CLI / admin route) may
# import them; nothing else may read them or the workbook parser.
_ALLOWED = {
    "tools/reference/legacy.py", "tools/core/models.py", "tools/ingestion/workbook.py",
    "tools/ingestion/__init__.py", "server/cli.py", "server/routes.py",
}
_FORBIDDEN = re.compile(r"\b(PermittedValue|MirrorSirg?|ExpressionTemplate|ingest_workbook|load_workbook)\b"
                        r"|tools\.ingestion\.workbook")


def test_no_module_outside_the_repository_reads_workbook_reference_data() -> None:
    offenders = []
    for path in [*ROOT.glob("tools/**/*.py"), *ROOT.glob("server/**/*.py"), ROOT / "agent.py"]:
        rel = path.relative_to(ROOT).as_posix()
        if rel in _ALLOWED or rel.startswith("tools/sirdb/"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _FORBIDDEN.search(line) and "openpyxl.Workbook" not in line:
                offenders.append(f"{rel}:{n}: {line.strip()}")
    assert offenders == []


# --------------------------------------------------------------------------- #
# PostgreSQL: migrations, sirdb repository, parity
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def migrated_url() -> str:
    from scripts.migrate import run
    from tests.pg import create_database

    url = sqlalchemy_url(create_database("ccre_migrate"))
    run(url)
    return url


@needs_pg
def test_migrations_reproduce_the_models_and_apply_sirdb(migrated_url: str) -> None:
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import inspect

    from tools.core.db import make_engine
    from tools.core.models import APP_SCHEMA, Base

    engine = make_engine(migrated_url)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(conn, opts={
            "include_schemas": True, "compare_type": True,
            "include_name": lambda name, type_, _p: name == APP_SCHEMA if type_ == "schema" else True})
        assert compare_metadata(ctx, Base.metadata) == []
    tables = set(inspect(engine).get_table_names(schema="sirdb"))
    assert {"import_rule", "sir_reference", "technical_sirg", "schema_migration"} <= tables


@needs_pg
def test_migrate_is_idempotent(migrated_url: str) -> None:
    from scripts.migrate import run

    assert run(migrated_url)["sirdb"] == []


@pytest.fixture(scope="module")
def both_sources_url() -> str:
    if not sorted(REFERENCE.glob("M2c*.xlsx")) or not sorted(REFERENCE.glob("sir-configuration*")):
        pytest.skip("needs the M2C workbook and the sir-configuration package in Reference/")
    from scripts.reference_parity import load_both
    from tests.pg import create_database
    from tools.core.config import SETTINGS

    url = sqlalchemy_url(create_database("ccre_parity"))
    load_both(url, SETTINGS.reference_dir)
    return url


@needs_pg
def test_sirdb_repository_serves_v_import_final(both_sources_url: str) -> None:
    from tools.reference import SirdbReferenceRepository
    from tools.core.db import make_engine

    repo = SirdbReferenceRepository(make_engine(both_sources_url))
    rows = repo.baseline_rules()
    assert rows and all(r.direction == "Import" and r.row_no for r in rows)
    bg = repo.baseline_rules("BG")
    assert bg and {r.ctry_cd for r in bg} == {"BG"}
    assert repo.workbook_version() and repo.permitted_values().get("currency")
    assert repo.mirror_sir() and repo.mirror_sirg("BG") and repo.expression_templates()


@needs_pg
def test_reference_parity_legacy_vs_sirdb(both_sources_url: str) -> None:
    from scripts.reference_parity import report

    rep = report(both_sources_url)
    assert rep.differences == [], "\n".join(d.line() for d in rep.differences)
    assert rep.counts["import_rows"][0] == rep.counts["import_rows"][1] > 0
    assert rep.accepted.get("TBD_KEY_ROWS") == 2  # IL rows 32 and 33 (docs/adr/0003)


def test_parity_reports_a_field_difference() -> None:
    from tools.reference.base import ReferenceRule

    def rule(**kw):  # noqa: ANN001, ANN202
        base = dict(id="x", row_no=5, direction="Import", region="EU", ctry_cd="BG", shipment_type="B2C",
                    effective_date=None, expiry_date=None, network_product_codes=None, value_basis="DV",
                    currency="BGN", min_value=None, max_value=None, min_weight=None, max_weight=None,
                    other_logic=None, country_hold_cd=None, global_hold_cd=None, sirg_cd="IOSS",
                    doc_reference=None)
        return ReferenceRule(**{**base, **kw})

    class _Repo:
        def __init__(self, rows):  # noqa: ANN001
            self.rows = rows

        def baseline_rules(self, country=None):  # noqa: ANN001, ANN202
            return self.rows

        def permitted_values(self, version=None):  # noqa: ANN001, ANN202
            return {}

        def mirror_sir(self, version=None):  # noqa: ANN001, ANN202
            return []

        def mirror_sirg(self, country=None, version=None):  # noqa: ANN001, ANN202
            return []

        def expression_templates(self, version=None):  # noqa: ANN001, ANN202
            return []

    rep = compare(_Repo([rule()]), _Repo([rule(currency="EUR")]))
    assert [(d.field, d.legacy, d.sirdb) for d in rep.differences] == [("currency", "BGN", "EUR")]
    assert compare(_Repo([rule(direction="Export")]), _Repo([])).accepted["EXPORT_ROWS"] == 1
