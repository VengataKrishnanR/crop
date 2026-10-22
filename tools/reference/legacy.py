"""Reference data from the app's own workbook ingestion (``REFERENCE_SOURCE=legacy``).

Kept for one release beside sirdb (docs/adr/0003). It reproduces exactly what the
callers queried before the repository existed: the newest case-less rule set is
the baseline, and lists / mirror / palette are read from their ingestion tables.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from tools.core.models import ExpressionTemplate, MirrorSir, MirrorSirg, PermittedValue, Rule, RuleSet

from .base import MirrorSirgRow, MirrorSirRow, ReferenceBinding, ReferenceRule


class LegacyReferenceRepository:
    source = "legacy"

    def __init__(self, session: Session) -> None:
        self._session = session

    def baseline_rule_set(self, country: Optional[str] = None) -> Optional[RuleSet]:
        """The newest workbook rule set not owned by a case (what ``ccre bootstrap`` loads)."""
        stmt = select(RuleSet).where(RuleSet.case_id.is_(None)).order_by(RuleSet.created_at.desc())
        if country:
            stmt = stmt.where(RuleSet.id.in_(select(Rule.rule_set_id).where(Rule.ctry_cd == country.upper())))
        return self._session.execute(stmt.limit(1)).scalar_one_or_none()

    def workbook_version(self) -> Optional[str]:
        base = self.baseline_rule_set()
        if base is not None and base.source_version:
            return base.source_version
        return self._session.execute(
            select(MirrorSirg.source_version).order_by(MirrorSirg.id.desc()).limit(1)).scalar_one_or_none()

    def baseline_rules(self, country: Optional[str] = None) -> list[ReferenceRule]:
        base = self.baseline_rule_set(country)
        if base is None:
            return []
        stmt = select(Rule).where(Rule.rule_set_id == base.id).options(selectinload(Rule.bindings))
        if country:
            stmt = stmt.where(Rule.ctry_cd == country.upper())
        return [_to_reference(r) for r in self._session.execute(stmt.order_by(Rule.row_no)).scalars()]

    def permitted_values(self, version: Optional[str] = None) -> dict[str, set[str]]:
        stmt = select(PermittedValue.field, PermittedValue.value)
        if version:
            stmt = stmt.where(PermittedValue.source_version == version)
        out: dict[str, set[str]] = {}
        for field, value in self._session.execute(stmt).all():
            out.setdefault(field, set()).add(value)
        return out

    def mirror_sir(self, version: Optional[str] = None) -> list[MirrorSirRow]:
        stmt = select(MirrorSir).order_by(MirrorSir.id)
        if version:
            stmt = stmt.where(MirrorSir.source_version == version)
        return [MirrorSirRow(sir_id=m.sir_id, cmpt_nm=m.cmpt_nm, nm=m.nm, dsc=m.dsc)
                for m in self._session.execute(stmt).scalars()]

    def mirror_sirg(self, country: Optional[str] = None, version: Optional[str] = None) -> list[MirrorSirgRow]:
        stmt = select(MirrorSirg).order_by(MirrorSirg.id)
        if country:
            stmt = stmt.where(MirrorSirg.ctry_cd == country.upper())
        if version:
            stmt = stmt.where(MirrorSirg.source_version == version)
        return [MirrorSirgRow(sirg_id=m.sirg_id, sirg_cd=m.sirg_cd, sirg_nm=m.sirg_nm, sirg_dsc=m.sirg_dsc,
                              ctry_cd=m.ctry_cd, proc_lvl_cd=m.proc_lvl_cd, cmpt_nm=m.cmpt_nm, sir_id=m.sir_id)
                for m in self._session.execute(stmt).scalars()]

    def expression_templates(self, version: Optional[str] = None) -> list[str]:
        stmt = select(ExpressionTemplate.expression).order_by(ExpressionTemplate.id)
        if version:
            stmt = stmt.where(ExpressionTemplate.source_version == version)
        return list(self._session.execute(stmt).scalars())


def _to_reference(r: Rule) -> ReferenceRule:
    return ReferenceRule(
        id=r.id, row_no=r.row_no, direction=r.direction, region=r.region, ctry_cd=r.ctry_cd,
        shipment_type=r.shipment_type, effective_date=r.effective_date, expiry_date=r.expiry_date,
        network_product_codes=r.network_product_codes, value_basis=r.value_basis, currency=r.currency,
        min_value=r.min_value, max_value=r.max_value, min_weight=r.min_weight, max_weight=r.max_weight,
        other_logic=r.other_logic, country_hold_cd=r.country_hold_cd, global_hold_cd=r.global_hold_cd,
        sirg_cd=r.sirg_cd, doc_reference=r.doc_reference,
        bindings=tuple(ReferenceBinding(
            sirg_cd=b.sirg_cd, sir_id=b.sir_id, cmpt_nm=b.cmpt_nm,
            waived_if_whitelisted=bool(b.waived_if_whitelisted), waived_to_validate=bool(b.waived_to_validate),
            check_service_code=b.check_service_code, attribute_ids=tuple(b.attribute_ids or []), sirg_id=b.sirg_id,
        ) for b in r.bindings),
    )
