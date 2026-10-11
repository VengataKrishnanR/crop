"""Export builder.

Produces what Support needs to carry a change into CCRE themselves: the package
files, the regenerated workbook and an evidence pack. Output is deterministic --
the same rule set always produces byte-identical CSVs and the same workbook
layout -- so two exports can be diffed.

Keys are *regenerated* here rather than copied, which is what retires the
hand-typed-key defect class and makes row order stop mattering.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import Approval, OnboardingCase, Rule, RuleSet, SirgDef, ValidationRun

WORKBOOK_IMPORT_HEADERS = [
    "Region", "Country", "B2B/B2C", "Effective Date (DD-MM-YYY)", "Date of Expiry (DD-MM-YYY)",
    "Network Product Code", "Declared Value/ Intristic Value", "Currency", "Min Value (>=)",
    "Max Value (<=)", "Shipt Weight (kg) (>=)", "Shipt Weight (kg) (<=)", "Other Logic",
    "Country Hold Code", "Global Hold Code", "Document Reference", "SIRG Document Reference",
]

SIR_REFERENCE_HEADERS = [
    "Document Reference", "SIR Document Reference", "Waived if Whitelisted", "Waived to Validate",
    "Check if Service Code=", "CmptNm", "SIR Technical Id", "AttributeID",
]


@dataclass
class ExportBundle:
    rule_set_id: str
    rule_set_version: str
    import_rows: list[dict[str, str]]
    sir_reference_rows: list[dict[str, str]]
    mapping_csv: str
    evidence: dict[str, Any]

    def import_csv(self) -> str:
        return _to_csv(WORKBOOK_IMPORT_HEADERS, self.import_rows)

    def sir_reference_csv(self) -> str:
        return _to_csv(SIR_REFERENCE_HEADERS, self.sir_reference_rows)


def _to_csv(headers: list[str], rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=headers, lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({h: row.get(h, "") for h in headers})
    return buffer.getvalue()


def _fmt_date(value: Optional[dt.date]) -> str:
    return value.strftime("%d-%m-%Y") if value else ""


def _fmt_num(value: Optional[float]) -> str:
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else str(value)


def build_export(session: Session, rule_set_id: str) -> ExportBundle:
    rule_set = session.get(RuleSet, rule_set_id)
    if rule_set is None:
        raise LookupError(f"no such rule set: {rule_set_id}")

    rules = list(session.execute(
        select(Rule)
        .where(Rule.rule_set_id == rule_set_id)
        .options(selectinload(Rule.bindings))
        .order_by(Rule.ctry_cd, Rule.sirg_cd, Rule.row_no)
    ).scalars())

    sirg_id_by_cd = {
        cd: sid for cd, sid in session.execute(select(SirgDef.cd, SirgDef.id)).all()
    }

    import_rows: list[dict[str, str]] = []
    reference_rows: list[dict[str, str]] = []
    mapping_rows: list[tuple[str, str, str, str]] = []

    for rule in rules:
        # Regenerated, not copied.
        doc_ref = rule.generated_doc_reference
        sirg_ref = f"{rule.ctry_cd}|{rule.direction}|{rule.sirg_cd}" if rule.sirg_cd else ""

        import_rows.append({
            "Region": rule.region or "",
            "Country": rule.ctry_cd,
            "B2B/B2C": rule.shipment_type or "",
            "Effective Date (DD-MM-YYY)": _fmt_date(rule.effective_date),
            "Date of Expiry (DD-MM-YYY)": _fmt_date(rule.expiry_date),
            "Network Product Code": rule.network_product_codes or "",
            "Declared Value/ Intristic Value": rule.value_basis or "",
            "Currency": rule.currency or "",
            "Min Value (>=)": _fmt_num(rule.min_value),
            "Max Value (<=)": _fmt_num(rule.max_value),
            "Shipt Weight (kg) (>=)": _fmt_num(rule.min_weight),
            "Shipt Weight (kg) (<=)": _fmt_num(rule.max_weight),
            "Other Logic": rule.other_logic or "",
            "Country Hold Code": rule.country_hold_cd or "",
            "Global Hold Code": rule.global_hold_cd or "",
            "Document Reference": doc_ref,
            "SIRG Document Reference": sirg_ref,
        })

        for binding in rule.bindings:
            reference_rows.append({
                "Document Reference": doc_ref,
                "SIR Document Reference": (
                    f"{rule.ctry_cd}|{rule.direction}|{rule.sirg_cd or ''}|{binding.cmpt_nm or ''}"
                ),
                "Waived if Whitelisted": "Y" if binding.waived_if_whitelisted else "N",
                "Waived to Validate": "Y" if binding.waived_to_validate else "N",
                "Check if Service Code=": binding.check_service_code or "",
                "CmptNm": binding.cmpt_nm or "",
                "SIR Technical Id": binding.sir_id or "",
                "AttributeID": "&".join(binding.attribute_ids or []),
            })
            sirg_id = binding.sirg_id or sirg_id_by_cd.get(binding.sirg_cd or rule.sirg_cd or "")
            if sirg_id and binding.sir_id:
                mapping_rows.append((rule.ctry_cd, "IMP_CLR", sirg_id, binding.sir_id))

    # Package mapping CSV, matching the upstream column names exactly.
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "CtryProc.DhlCtryCd", "CtryProc.ProcLvlCd", "ShpInfReqGrpDef.Id",
        "ShpInfReqDef.Id", "ShpInfReqDef.FlNm",
    ])
    for ctry, proc, sirg_id, sir_id in sorted(set(mapping_rows)):
        writer.writerow([ctry, proc, sirg_id, sir_id, f"{sir_id}.json"])

    evidence = _build_evidence(session, rule_set, rules)

    return ExportBundle(
        rule_set_id=rule_set_id,
        rule_set_version=rule_set.version,
        import_rows=import_rows,
        sir_reference_rows=reference_rows,
        mapping_csv=buffer.getvalue(),
        evidence=evidence,
    )


def _build_evidence(session: Session, rule_set: RuleSet, rules: list[Rule]) -> dict[str, Any]:
    """The evidence pack contents, as data. Rendering to XLSX is a separate concern."""
    case: Optional[OnboardingCase] = (
        session.get(OnboardingCase, rule_set.case_id) if rule_set.case_id else None
    )
    approvals = []
    validation: dict[str, Any] = {}

    if case is not None:
        approvals = [
            {
                "stage": a.stage, "actor": a.actor, "role": a.role, "decision": a.decision,
                "comment": a.comment, "at": a.at.isoformat(), "rule_set_version": a.rule_set_version,
            }
            for a in sorted(case.approvals, key=lambda x: x.at)
        ]
        run = session.execute(
            select(ValidationRun)
            .where(ValidationRun.rule_set_id == rule_set.id)
            .order_by(ValidationRun.at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if run is not None:
            validation = {
                "at": run.at.isoformat(),
                "blockers": run.blocker_count,
                "cautions": run.caution_count,
                "infos": run.info_count,
                "findings": run.findings,
            }

    return {
        "case": None if case is None else {
            "code": case.code,
            "country": case.ctry_cd,
            "title": case.title,
            "gccp_ref": case.gccp_ref,
            "state": case.state,
            "requested_rtp": case.requested_rtp.isoformat() if case.requested_rtp else None,
            "approved_rtp": case.approved_rtp.isoformat() if case.approved_rtp else None,
        },
        "rule_set": {
            "id": rule_set.id,
            "version": rule_set.version,
            "sealed": rule_set.sealed,
            "created_at": rule_set.created_at.isoformat(),
            "created_by": rule_set.created_by,
        },
        "change_summary": [
            {
                "country": r.ctry_cd,
                "requirement_group": r.sirg_cd,
                "shipment_type": r.shipment_type,
                "condition": r.other_logic,
                "requirements_raised": [b.cmpt_nm for b in r.bindings],
            }
            for r in rules
        ],
        "signoffs": approvals,
        "validation": validation,
    }


def seal(session: Session, rule_set_id: str, actor: str) -> RuleSet:
    """Freeze a rule set. Sealed sets are immutable; a change forks a new version."""
    rule_set = session.get(RuleSet, rule_set_id)
    if rule_set is None:
        raise LookupError(f"no such rule set: {rule_set_id}")
    rule_set.sealed = True
    session.flush()
    return rule_set


def fork(session: Session, rule_set_id: str, new_version: str, actor: str) -> RuleSet:
    """Copy a rule set into a new editable version, leaving the original intact."""
    source = session.get(RuleSet, rule_set_id)
    if source is None:
        raise LookupError(f"no such rule set: {rule_set_id}")

    clone = RuleSet(
        case_id=source.case_id,
        version=new_version,
        label=f"Forked from {source.version}",
        created_by=actor,
        source_version=source.source_version,
        sealed=False,
    )
    session.add(clone)
    session.flush()

    rules = list(session.execute(
        select(Rule).where(Rule.rule_set_id == rule_set_id).options(selectinload(Rule.bindings))
    ).scalars())

    from .models import RuleBinding  # local import avoids a cycle at module load

    for rule in rules:
        copy = Rule(
            rule_set_id=clone.id, row_no=rule.row_no, direction=rule.direction, region=rule.region,
            ctry_cd=rule.ctry_cd, shipment_type=rule.shipment_type,
            effective_date=rule.effective_date, expiry_date=rule.expiry_date,
            network_product_codes=rule.network_product_codes, value_basis=rule.value_basis,
            currency=rule.currency, min_value=rule.min_value, max_value=rule.max_value,
            min_weight=rule.min_weight, max_weight=rule.max_weight, other_logic=rule.other_logic,
            country_hold_cd=rule.country_hold_cd, global_hold_cd=rule.global_hold_cd,
            sirg_cd=rule.sirg_cd, doc_reference=rule.doc_reference,
        )
        session.add(copy)
        session.flush()
        for binding in rule.bindings:
            session.add(RuleBinding(
                rule_id=copy.id, sirg_cd=binding.sirg_cd, sirg_id=binding.sirg_id,
                sir_id=binding.sir_id, cmpt_nm=binding.cmpt_nm,
                waived_if_whitelisted=binding.waived_if_whitelisted,
                waived_to_validate=binding.waived_to_validate,
                check_service_code=binding.check_service_code,
                attribute_ids=list(binding.attribute_ids or []),
            ))
    session.flush()
    return clone
