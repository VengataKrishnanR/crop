"""An in-memory snapshot of everything the checks need.

Checks are pure functions of a snapshot so they can be unit-tested without a
database and so a whole validation run is one read pass rather than N queries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from tools.core.models import (
    ConfigPackage, CtryProcMapping, ExpressionTemplate, MirrorSir, MirrorSirg,
    PermittedValue, ReleaseNoteEntry, Rule, RuleSet, SirAttribute, SirDef, SirgDef,
)


@dataclass
class Snapshot:
    package_version: str = ""
    workbook_version: str = ""

    # catalog
    sirg_by_id: dict[str, SirgDef] = field(default_factory=dict)
    sirg_id_by_cd: dict[str, str] = field(default_factory=dict)
    sir_by_id: dict[str, SirDef] = field(default_factory=dict)
    attributes_by_sir: dict[str, set[str]] = field(default_factory=dict)
    mappings: set[tuple[str, str, str, str]] = field(default_factory=set)
    mapping_rows: list[CtryProcMapping] = field(default_factory=list)
    release_entries: list[ReleaseNoteEntry] = field(default_factory=list)

    # workbook mirror
    mirror_sir: list[MirrorSir] = field(default_factory=list)
    mirror_sirg: list[MirrorSirg] = field(default_factory=list)

    # rules under review
    rules: list[Rule] = field(default_factory=list)
    rule_set: Optional[RuleSet] = None

    # lookups
    permitted: dict[str, set[str]] = field(default_factory=dict)
    templates: list[str] = field(default_factory=list)

    # ---- derived ----

    @property
    def active_sir_ids(self) -> set[str]:
        """A SIR is active only where the mapping table reaches it.

        The package carries no status field, so reachability is the definition.
        """
        return {m[3] for m in self.mappings}

    @property
    def mapped_countries(self) -> set[str]:
        return {m[0] for m in self.mappings}

    def sirg_ids_for_country(self, ctry: str) -> set[str]:
        return {m[2] for m in self.mappings if m[0] == ctry}


def load_snapshot(
    session: Session,
    rule_set_id: Optional[str] = None,
    package_version: Optional[str] = None,
    workbook_version: Optional[str] = None,
) -> Snapshot:
    snap = Snapshot()

    # Resolve the rule set first: it records which workbook version it came from,
    # which is more trustworthy than guessing the newest mirror in the database.
    if rule_set_id:
        snap.rule_set = session.get(RuleSet, rule_set_id)
        snap.rules = list(session.execute(
            select(Rule).where(Rule.rule_set_id == rule_set_id).options(selectinload(Rule.bindings))
        ).scalars())
        if workbook_version is None and snap.rule_set is not None:
            workbook_version = snap.rule_set.source_version

    if package_version is None:
        latest = session.execute(
            select(ConfigPackage).order_by(ConfigPackage.ingested_at.desc()).limit(1)
        ).scalar_one_or_none()
        package_version = latest.version if latest else ""
    snap.package_version = package_version or ""

    if package_version:
        for sirg in session.execute(
            select(SirgDef).where(SirgDef.package_version == package_version)
        ).scalars():
            snap.sirg_by_id[sirg.id] = sirg
            snap.sirg_id_by_cd.setdefault(sirg.cd, sirg.id)

        for sir in session.execute(
            select(SirDef).where(SirDef.package_version == package_version)
        ).scalars():
            snap.sir_by_id[sir.id] = sir

        for att in session.execute(
            select(SirAttribute.sir_id, SirAttribute.att_id)
            .where(SirAttribute.package_version == package_version)
        ).all():
            snap.attributes_by_sir.setdefault(att[0], set()).add(att[1])

        for row in session.execute(
            select(CtryProcMapping).where(CtryProcMapping.package_version == package_version)
        ).scalars():
            snap.mapping_rows.append(row)
            snap.mappings.add((row.ctry_cd, row.proc_lvl_cd, row.sirg_id, row.sir_id))

        snap.release_entries = list(session.execute(
            select(ReleaseNoteEntry).where(ReleaseNoteEntry.package_version == package_version)
        ).scalars())

    if workbook_version is None:
        newest = session.execute(
            select(MirrorSirg.source_version).order_by(MirrorSirg.id.desc()).limit(1)
        ).scalar_one_or_none()
        workbook_version = newest or ""
    snap.workbook_version = workbook_version or ""

    if workbook_version:
        snap.mirror_sir = list(session.execute(
            select(MirrorSir).where(MirrorSir.source_version == workbook_version)
        ).scalars())
        snap.mirror_sirg = list(session.execute(
            select(MirrorSirg).where(MirrorSirg.source_version == workbook_version)
        ).scalars())
        for row in session.execute(
            select(PermittedValue).where(PermittedValue.source_version == workbook_version)
        ).scalars():
            snap.permitted.setdefault(row.field, set()).add(row.value)
        snap.templates = [
            t for t in session.execute(
                select(ExpressionTemplate.expression)
                .where(ExpressionTemplate.source_version == workbook_version)
            ).scalars()
        ]

    return snap
