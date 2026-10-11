"""Validator tests.

Two layers: hand-built fixtures that isolate one check each, and an integration
run over the real artifacts whose findings are asserted by code.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from tools.core.models import MirrorSir, MirrorSirg, Rule, RuleBinding
from tools.validation import load_snapshot, run_checks, validate_rule_set

from conftest import add_rule, make_rule_set


def _codes(report) -> set[str]:  # noqa: ANN001
    return {f.code.split("/")[0] for f in report.findings}


def _by_code(report, code: str):  # noqa: ANN001
    return [f for f in report.findings if f.code.startswith(code)]


# --------------------------------------------------------------------------- #
# Isolated checks
# --------------------------------------------------------------------------- #

def test_clean_rule_set_has_no_blockers(session: Session, tiny_catalog: dict) -> None:
    rule_set = make_rule_set(session)
    add_rule(session, rule_set.id, sirg_cd="IOSS", sir_id="sir-ioss-bg", currency="EUR")
    report, _ = validate_rule_set(session, rule_set.id, persist=False)
    assert report.blockers == [], [f.message for f in report.blockers]
    assert report.is_clean


def test_unknown_requirement_group_blocks(session: Session, tiny_catalog: dict) -> None:
    rule_set = make_rule_set(session)
    rule = add_rule(session, rule_set.id, sirg_cd="IOSS", bind=False)
    session.add(RuleBinding(
        rule_id=rule.id, sirg_cd="NOPE", sirg_id="sirg-does-not-exist", sir_id="sir-ioss-bg",
    ))
    session.commit()
    report, _ = validate_rule_set(session, rule_set.id, persist=False)
    assert "CHK002" in _codes(report)
    assert any(f.severity == "blocker" for f in _by_code(report, "CHK002"))


def test_missing_definition_blocks(session: Session, tiny_catalog: dict) -> None:
    rule_set = make_rule_set(session)
    add_rule(session, rule_set.id, sir_id="sir-not-shipped")
    report, _ = validate_rule_set(session, rule_set.id, persist=False)
    blockers = _by_code(report, "CHK003")
    assert blockers and blockers[0].severity == "blocker"
    assert "rebuild" in (blockers[0].evidence or "").lower()


def test_country_absent_from_package_blocks(session: Session, tiny_catalog: dict) -> None:
    """The BG situation: rules exist, the package has never heard of the country."""
    rule_set = make_rule_set(session)
    add_rule(session, rule_set.id, ctry_cd="XX", sir_id="sir-ioss-bg")
    report, _ = validate_rule_set(session, rule_set.id, persist=False)
    findings = _by_code(report, "CHK015")
    assert findings and findings[0].severity == "blocker"
    assert "XX" in findings[0].subjects


def test_unresolvable_attribute_id_blocks(session: Session, tiny_catalog: dict) -> None:
    rule_set = make_rule_set(session)
    rule = add_rule(session, rule_set.id, bind=False)
    session.add(RuleBinding(
        rule_id=rule.id, sirg_cd="IOSS", sirg_id="sirg-ioss", sir_id="sir-ioss-bg",
        attribute_ids=["att-ioss-1", "att-not-real"],
    ))
    session.commit()
    report, _ = validate_rule_set(session, rule_set.id, persist=False)
    findings = _by_code(report, "CHK005")
    assert findings and findings[0].severity == "blocker"
    # The valid one is not reported.
    assert "att-not-real" in " ".join(findings[0].subjects)
    assert "att-ioss-1" not in " ".join(findings[0].subjects)


def test_rule_with_no_binding_blocks(session: Session, tiny_catalog: dict) -> None:
    rule_set = make_rule_set(session)
    add_rule(session, rule_set.id, bind=False)
    report, _ = validate_rule_set(session, rule_set.id, persist=False)
    findings = _by_code(report, "CHK009")
    assert findings and findings[0].severity == "blocker"


def test_bad_expression_blocks_and_precedence_cautions(
    session: Session, tiny_catalog: dict
) -> None:
    rule_set = make_rule_set(session)
    add_rule(session, rule_set.id, other_logic='serviceCodes.contains("DD")')
    add_rule(session, rule_set.id, sirg_cd="POAB", sir_id="sir-poab-bg", row_no=2,
             other_logic='OriginCountry=="TR"||OriginCountry=="SD" && serviceCodeList.contains("DD")')
    report, _ = validate_rule_set(session, rule_set.id, persist=False)
    expr = _by_code(report, "CHK010")
    assert any(f.severity == "blocker" for f in expr)
    assert any(f.severity == "caution" for f in expr)


def test_disallowed_currency_cautions(session: Session, tiny_catalog: dict) -> None:
    rule_set = make_rule_set(session)
    add_rule(session, rule_set.id, currency="XYZ")
    report, _ = validate_rule_set(session, rule_set.id, persist=False)
    findings = _by_code(report, "CHK012")
    assert findings and findings[0].severity == "caution"
    assert "XYZ" in findings[0].message


def test_hand_typed_reference_key_cautions(session: Session, tiny_catalog: dict) -> None:
    rule_set = make_rule_set(session)
    add_rule(session, rule_set.id, doc_reference="BG|Import|IOSS")
    report, _ = validate_rule_set(session, rule_set.id, persist=False)
    findings = _by_code(report, "CHK016")
    assert findings and findings[0].severity == "caution"
    assert "regenerates" in (findings[0].evidence or "")


def test_inactive_definitions_are_info_only(session: Session, tiny_catalog: dict) -> None:
    """Unmapped definitions are inactive, which is information not a defect."""
    from tools.core.models import SirDef

    session.add(SirDef(
        id="sir-orphan", package_version="t1", nm="Orphan - OLD", cmpt_nm="ORPH",
    ))
    session.commit()
    rule_set = make_rule_set(session)
    add_rule(session, rule_set.id)
    report, _ = validate_rule_set(session, rule_set.id, persist=False)
    findings = _by_code(report, "CHK004")
    assert findings and findings[0].severity == "info"
    assert findings[0].counts["inactive"] == 1


def test_duplicate_mirror_rows_caution(session: Session, tiny_catalog: dict) -> None:
    for _ in range(2):
        session.add(MirrorSirg(
            sirg_id="sirg-ioss", sirg_cd="IOSS", sirg_nm="Import One-Stop Shop",
            ctry_cd="BG", proc_lvl_cd="IMP_CLR", sir_id="sir-ioss-bg", source_version="w1",
        ))
    session.commit()
    snapshot = load_snapshot(session, package_version="t1", workbook_version="w1")
    report = run_checks(snapshot, only=["CHK008"])
    assert len(report.cautions) == 1


def test_validation_run_is_persisted_as_evidence(session: Session, tiny_catalog: dict) -> None:
    from tools.core.models import ValidationRun

    rule_set = make_rule_set(session)
    add_rule(session, rule_set.id, sir_id="sir-not-shipped")
    report, run_id = validate_rule_set(session, rule_set.id, persist=True)
    session.commit()
    assert run_id
    run = session.get(ValidationRun, run_id)
    assert run.blocker_count == len(report.blockers)
    assert run.findings


def test_every_registered_check_runs(session: Session, tiny_catalog: dict) -> None:
    from tools.validation import available_checks

    rule_set = make_rule_set(session)
    add_rule(session, rule_set.id)
    report, _ = validate_rule_set(session, rule_set.id, persist=False)
    assert set(report.checks_run) == set(available_checks())


# --------------------------------------------------------------------------- #
# Integration: the real artifacts
# --------------------------------------------------------------------------- #

def test_real_artifacts_produce_the_expected_finding_classes(
    session: Session, ingested: dict
) -> None:
    report, _ = validate_rule_set(session, ingested["rule_set_id"], persist=False)
    codes = _codes(report)
    # Cross-artifact drift between workbook 2.10.9 and package 2.10.4.
    assert "CHK001" in codes
    # BG, BR, CO, EC, NA, PL have rules but no package mapping.
    assert "CHK015" in codes
    # The Other Logic palette's comma syntax would not parse.
    assert "CHK011" in codes
    # BGN is not in the permitted currency list.
    assert "CHK012" in codes
    assert not report.is_clean


def test_real_artifacts_flag_rule_countries_absent_from_the_package(
    session: Session, ingested: dict
) -> None:
    """Three of the 21 countries with rules have no package mapping at all."""
    report, _ = validate_rule_set(session, ingested["rule_set_id"], persist=False)
    findings = _by_code(report, "CHK015")
    assert findings
    assert set(findings[0].subjects) == {"BG", "CZ", "SK"}


def test_mirror_tab_names_more_unmapped_countries_than_the_rule_rows(
    session: Session, ingested: dict
) -> None:
    """The workbook's catalogue mirror reaches six countries the package does not.

    A different set from CHK015: the mirror covers countries that have catalogue
    entries but no authored rule rows in the Import tab.
    """
    from sqlalchemy import select

    from tools.core.models import CtryProcMapping, MirrorSirg

    mirror = {
        c for c in session.execute(select(MirrorSirg.ctry_cd).distinct()).scalars() if c
    }
    mapped = {
        c for c in session.execute(select(CtryProcMapping.ctry_cd).distinct()).scalars() if c
    }
    assert mirror - mapped == {"BG", "BR", "CO", "EC", "NA", "PL"}


def test_real_artifacts_measure_the_known_drift(session: Session, ingested: dict) -> None:
    report, _ = validate_rule_set(session, ingested["rule_set_id"], persist=False)
    drift = _by_code(report, "CHK001")
    assert drift
    counts = drift[0].counts
    # Measured between the two supplied artifacts.
    assert counts["matched"] == 717
    assert counts["workbook_only"] == 286
    assert counts["package_only"] == 134   # 135 raw, less the blank working-note row


def test_real_bg_ioss_expression_is_the_stale_one(session: Session, ingested: dict) -> None:
    """The validator cannot know the agreed expression -- but it can see the gap."""
    from sqlalchemy import select

    rule = session.execute(
        select(Rule).where(Rule.ctry_cd == "BG", Rule.sirg_cd == "IOSS")
    ).scalar_one()
    assert rule.other_logic == '!serviceCodeList.contains("DD")'
    # Its binding carries no waiver, contradicting what Support stated.
    binding = rule.bindings[0]
    assert binding.waived_to_validate is False
