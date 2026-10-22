"""Ingestion tests against the real artifacts.

The asserted numbers are the measured contents of the two files in ``Reference/``.
If a newer package or workbook is dropped in, these become the diff.
"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tools.ingestion import ingest_package, ingest_workbook
from tools.ingestion.package import parse_release_notes
from tools.ingestion.workbook import _split_attribute_ids
from tools.core.models import (
    CtryProcMapping, MirrorSirg, PermittedValue, Rule, RuleBinding, SirAttribute, SirDef, SirgDef,
)

# Measured from sir-configuration-v.2.10.4-beta.2
PKG_SIRG = 83
PKG_SIR = 934
PKG_MAPPINGS = 851      # 852 CSV rows, one of which is a hand-typed working note
PKG_COUNTRIES = 90      # the 91st distinct value in the CSV is blank

# Measured from M2c_6_5_ver_1_W29_2.10.9-beta.2
WB_RULES = 56
WB_MIRROR_SIR = 984
WB_MIRROR_SIRG = 1004


def test_package_counts(session: Session, real_package_path: Path) -> None:
    result = ingest_package(session, real_package_path)
    session.commit()
    assert result.sirg == PKG_SIRG
    assert result.sir == PKG_SIR
    assert result.mappings == PKG_MAPPINGS
    assert result.unparseable == []
    assert result.version.startswith("2.10.4")


def test_working_note_in_the_mapping_csv_is_captured_not_dropped(
    session: Session, real_package_path: Path
) -> None:
    """The shipped CSV has prose typed where a data row belongs."""
    result = ingest_package(session, real_package_path)
    session.commit()
    assert len(result.malformed_mappings) == 1
    assert "pending" in result.malformed_mappings[0].lower()


def test_package_countries_and_proc_level(session: Session, real_package_path: Path) -> None:
    ingest_package(session, real_package_path)
    session.commit()
    countries = session.execute(select(CtryProcMapping.ctry_cd).distinct()).scalars()
    assert len({c for c in countries if c}) == PKG_COUNTRIES
    levels = session.execute(select(CtryProcMapping.proc_lvl_cd).distinct()).scalars()
    assert {level for level in levels if level} == {"IMP_CLR"}


def test_bg_is_absent_from_the_package(session: Session, real_package_path: Path) -> None:
    """The gap that blocks BG testing, asserted directly."""
    ingest_package(session, real_package_path)
    session.commit()
    count = session.execute(
        select(func.count()).select_from(CtryProcMapping).where(CtryProcMapping.ctry_cd == "BG")
    ).scalar_one()
    assert count == 0


def test_nested_entities_are_flattened_recursively(session: Session, real_package_path: Path) -> None:
    """A one-level walk misses most attributes; this definition nests three deep."""
    ingest_package(session, real_package_path)
    session.commit()
    sir_id = "f57a161a-28b2-42c9-b2a7-0539e2e86c95"
    attributes = list(session.execute(
        select(SirAttribute).where(SirAttribute.sir_id == sir_id)
    ).scalars())
    assert len(attributes) >= 10
    # Attributes exist below the first Ent level.
    assert any(a.ent_path.count("/") >= 3 for a in attributes)
    # Known deep attribute ids are reachable.
    ids = {a.att_id for a in attributes}
    assert "60fd6f23-847f-4eab-a880-2ed1c8ef0244" in ids
    assert "3fc006ce-ecfd-4fce-afae-d23b4b7587bc" in ids


def test_message_positions_are_preserved(session: Session, real_package_path: Path) -> None:
    """AttMsgPos drives payload generation, so it must survive ingestion intact."""
    ingest_package(session, real_package_path)
    session.commit()
    row = session.execute(
        select(SirAttribute).where(SirAttribute.msg_positions.isnot(None)).limit(50)
    ).scalars()
    with_positions = [a for a in row if a.msg_positions]
    assert with_positions, "no attribute retained its message positions"
    sample = with_positions[0].msg_positions[0]
    assert "MsgTyCd" in sample


def test_package_ingest_is_idempotent(session: Session, real_package_path: Path) -> None:
    first = ingest_package(session, real_package_path)
    session.commit()
    second = ingest_package(session, real_package_path)
    session.commit()
    assert first.sirg == second.sirg
    assert session.execute(select(func.count()).select_from(SirgDef)).scalar_one() == PKG_SIRG
    assert session.execute(select(func.count()).select_from(CtryProcMapping)).scalar_one() == PKG_MAPPINGS


def test_workbook_counts(session: Session, real_workbook_path: Path) -> None:
    result = ingest_workbook(session, real_workbook_path)
    session.commit()
    assert result.rules == WB_RULES
    assert result.mirror_sir == WB_MIRROR_SIR
    assert result.mirror_sirg == WB_MIRROR_SIRG
    assert result.version.startswith("2.10.9")


def test_workbook_resolves_concatenate_keys_into_bindings(
    session: Session, real_workbook_path: Path
) -> None:
    """Bindings join by cached CONCATENATE value, not by row position."""
    result = ingest_workbook(session, real_workbook_path)
    session.commit()
    assert result.bindings > 0
    # Eight SIR Reference lines are used by no Import rule (rows 33, 52-56, 59, 60).
    assert len(result.orphan_bindings) == 8


def test_bg_rules_are_present_with_their_expressions(
    session: Session, real_workbook_path: Path
) -> None:
    ingest_workbook(session, real_workbook_path)
    session.commit()
    rules = list(session.execute(select(Rule).where(Rule.ctry_cd == "BG")).scalars())
    assert len(rules) == 2
    by_group = {r.sirg_cd: r for r in rules}
    assert set(by_group) == {"IOSS", "POAB"}
    assert by_group["POAB"].other_logic == 'serviceCodeList.contains("DD")'
    # The stale expression -- missing the matchCiMask SDT clause.
    assert by_group["IOSS"].other_logic == '!serviceCodeList.contains("DD")'
    assert by_group["IOSS"].currency == "BGN"


def test_bg_reference_key_was_hand_typed(session: Session, real_workbook_path: Path) -> None:
    """A 3-part key where the convention generates 4 parts."""
    ingest_workbook(session, real_workbook_path)
    session.commit()
    rule = session.execute(
        select(Rule).where(Rule.ctry_cd == "BG", Rule.sirg_cd == "IOSS")
    ).scalar_one()
    assert rule.doc_reference == "BG|Import|IOSS"
    assert rule.generated_doc_reference == "BG|Import||"
    assert rule.doc_reference != rule.generated_doc_reference


def test_permitted_values_are_captured(session: Session, real_workbook_path: Path) -> None:
    ingest_workbook(session, real_workbook_path)
    session.commit()
    currencies = {
        v for v in session.execute(
            select(PermittedValue.value).where(PermittedValue.field == "currency")
        ).scalars()
    }
    assert "EUR" in currencies
    # BGN is used by the BG rules but is not permitted -- CHK012 depends on this.
    assert "BGN" not in currencies


def test_export_tab_is_header_only(session: Session, real_workbook_path: Path) -> None:
    ingest_workbook(session, real_workbook_path)
    session.commit()
    exports = session.execute(
        select(func.count()).select_from(Rule).where(Rule.direction == "Export")
    ).scalar_one()
    assert exports == 0


def test_release_notes_parsing() -> None:
    text = (
        "Updated Existing SIRG with new JSON:\n"
        "AE\tPII\t\td6bea01a-c4ed-46dc-a1f8-5340da73bec1.json\t\n"
        "FR\tATP\t    88853a57-680d-4493-ac42-d00f2d70c308.json\n"
        "some prose that is not an entry\n"
    )
    entries = parse_release_notes(text)
    assert ("AE", "PII", "d6bea01a-c4ed-46dc-a1f8-5340da73bec1") in entries
    assert ("FR", "ATP", "88853a57-680d-4493-ac42-d00f2d70c308") in entries
    assert len(entries) == 2


def test_attribute_id_splitting_handles_double_ampersand() -> None:
    assert _split_attribute_ids("a&&b") == ["a", "b"]
    assert _split_attribute_ids("a & b &c") == ["a", "b", "c"]
    assert _split_attribute_ids("") == []
    assert _split_attribute_ids(None) == []


def test_zip_and_directory_ingest_agree(session: Session, real_package_path: Path, tmp_path: Path) -> None:
    """The reader must give identical results from a zip and an extracted tree."""
    import zipfile

    if real_package_path.suffix.lower() != ".zip":
        return
    from_zip = ingest_package(session, real_package_path, version="z")
    session.commit()

    extract_to = tmp_path / "extracted"
    with zipfile.ZipFile(real_package_path) as zf:
        zf.extractall(extract_to)
    inner = next(p for p in extract_to.iterdir() if p.is_dir())
    from_dir = ingest_package(session, inner, version="d")
    session.commit()

    assert (from_zip.sirg, from_zip.sir, from_zip.mappings) == \
           (from_dir.sirg, from_dir.sir, from_dir.mappings)
