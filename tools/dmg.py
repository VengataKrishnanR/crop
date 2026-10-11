"""DMG change email — template placeholders and how they are filled for an onboarding.

The CCRE team owns the template (subject, body, recipients). Placeholders are
written as ``{{name}}`` and filled from the onboarding's own records, so the
email states exactly what was approved: the requirement, the M2C rows and the
requirement definitions with their DMG message positions.
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from tools.core.models import DmgTemplate, OnboardingCase, Rule, SirAttribute
from tools.workflow.case_facts import case_rule_set, current_timeline, latest_requirement

DEFAULT_SUBJECT = "[DMG change] {{country}} — {{title}} ({{case_code}})"
DEFAULT_BODY = """Hello DMG team,

Please implement the DMG changes below for the {{country}} onboarding {{case_code}} — {{title}}.

Requirement
{{requirement_summary}}
  Requirement groups : {{requirement_groups}}
  Shipment type      : {{shipment_type}}
  Conditions         : {{conditions}}

M2C rule rows ({{rule_count}})
{{m2c_rules}}

Requirement definitions and DMG message positions
{{dmg_attributes}}

Planned go-live (RTP): {{planned_rtp}}
Business owner: {{business_owner}}

Prepared by {{prepared_by}} via the CCRE onboarding platform.
"""

PLACEHOLDERS: dict[str, str] = {
    "case_code": "Onboarding code, e.g. ONB-2026-DE-001",
    "country": "ISO-2 country code",
    "title": "Onboarding title",
    "requirement_summary": "The captured business requirement in one or two sentences",
    "requirement_groups": "Requirement group codes, e.g. POA, IOSS",
    "shipment_type": "B2B / B2C",
    "conditions": "Trigger conditions in plain words",
    "rule_count": "Number of M2C rows for the country",
    "m2c_rules": "One line per M2C row: group, shipment type, value band, condition",
    "dmg_attributes": "Requirement definitions with their attributes and DMG message positions",
    "planned_rtp": "Approved RTP date from the published timeline",
    "requested_rtp": "Requested go-live date",
    "business_owner": "Business owner",
    "prepared_by": "Who prepared the email",
}

_TOKEN = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def get_template(session: Session) -> DmgTemplate:
    tpl = session.get(DmgTemplate, 1)
    if tpl is None:
        tpl = DmgTemplate(id=1, subject=DEFAULT_SUBJECT, body=DEFAULT_BODY, to=[], cc=[], updated_by="default")
        session.add(tpl)
        session.flush()
    return tpl


def unknown_placeholders(text: str) -> list[str]:
    return sorted({m.group(1) for m in _TOKEN.finditer(text) if m.group(1) not in PLACEHOLDERS})


def _cond(c: dict[str, Any]) -> str:
    value = c.get("value")
    return f"{c.get('field')} {str(c.get('operator', '')).replace('_', ' ')}{'' if value in (None, '') else ' ' + str(value)}"


def values_for(session: Session, case: OnboardingCase, prepared_by: str) -> dict[str, str]:
    req = latest_requirement(session, case.id)
    structured = (req.structured if req else {}) or {}
    tl = current_timeline(session, case.id)
    planned = tl.milestones[-1].planned_end.isoformat() if tl is not None and tl.status == "APPROVED" and tl.milestones else "—"

    rows, attributes = [], []
    rs = case_rule_set(session, case)
    if rs is not None:
        rules = list(session.execute(
            select(Rule).where(Rule.rule_set_id == rs.id, Rule.ctry_cd == case.ctry_cd)
            .options(selectinload(Rule.bindings)).order_by(Rule.row_no)).scalars())
        for r in rules:
            band = "" if r.min_value is None and r.max_value is None else \
                f", value {r.min_value if r.min_value is not None else '0'}–{r.max_value if r.max_value is not None else '∞'} {r.currency or ''}".rstrip()
            rows.append(f"  - {r.sirg_cd or '?'} | {r.shipment_type or 'any'}{band} | {r.other_logic or 'no extra condition'}")
            for b in r.bindings:
                if not b.sir_id:
                    continue
                atts = list(session.execute(select(SirAttribute).where(SirAttribute.sir_id == b.sir_id)).scalars())
                pos = "; ".join(f"{a.nm} ({a.msg_positions or a.ent_path or 'n/a'})" for a in atts[:12]) or "no attributes"
                line = f"  - {b.cmpt_nm or b.sir_id} [{b.sirg_cd}]: {pos}"
                if line not in attributes:
                    attributes.append(line)

    return {
        "case_code": case.code, "country": case.ctry_cd, "title": case.title,
        "requirement_summary": structured.get("summary") or structured.get("expected_behaviour")
        or (req.text if req else "") or "—",
        "requirement_groups": ", ".join(structured.get("requirement_groups") or []) or "—",
        "shipment_type": structured.get("shipment_type") or "—",
        "conditions": "; ".join(_cond(c) for c in structured.get("conditions") or []) or "—",
        "rule_count": str(len(rows)),
        "m2c_rules": "\n".join(rows) or "  (no M2C rows yet)",
        "dmg_attributes": "\n".join(attributes) or "  (no requirement definitions bound yet)",
        "planned_rtp": planned,
        "requested_rtp": str(structured.get("requested_rtp") or case.requested_rtp or "—"),
        "business_owner": structured.get("business_owner") or case.business_owner or "—",
        "prepared_by": prepared_by,
    }


def fill(text: str, values: dict[str, str]) -> str:
    return _TOKEN.sub(lambda m: values.get(m.group(1), m.group(0)), text)
