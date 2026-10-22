"""Rule configuration — the M2C draft of one onboarding, row by row.

This is the working core of rule configuration:

* **Row checks** — every Import row and its SIR Reference bindings are checked as
  they are edited (permitted values, value/weight bands, dates, condition grammar,
  bindings, package coverage), so problems are fixed where they are made.
* **Changes** — the draft compared with the country's rows in the loaded M2C
  workbook: new, changed (field by field), unchanged and removed rows.
* **Package coverage** — the Technical SIR / Technical SIRG view: is every bound
  requirement definition shipped by the config package and mapped for the
  country? Gaps become a Support request.
* **Condition builder** — Other Logic built from plain choices, always valid.
* **M2C workbook** — the country's M2C generated with the workbook's own formula
  convention (``CONCATENATE`` document references, ``IF(Import!P<n>…)`` bindings),
  so the positions are correct by construction.
"""
from __future__ import annotations

import datetime as dt
import io
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from tools.core import grammar
from tools.core.export import SIR_REFERENCE_HEADERS, WORKBOOK_IMPORT_HEADERS
from tools.core.models import (
    ConfigPackage, CtryProcMapping, OnboardingCase, Rule, RuleBinding, RuleSet, SirAttribute, SirDef, SirgDef,
)
from tools.reference import get_reference

DEFAULT_PROC_LVL = "IMP_CLR"

#: Import-row fields an author edits, with their workbook column header.
RULE_FIELDS: dict[str, str] = {
    "region": "Region", "ctry_cd": "Country", "direction": "Direction", "shipment_type": "B2B/B2C",
    "effective_date": "Effective Date", "expiry_date": "Date of Expiry",
    "network_product_codes": "Network Product Code", "value_basis": "DV/IV", "currency": "Currency",
    "min_value": "Min Value (>=)", "max_value": "Max Value (<=)", "min_weight": "Weight (kg) (>=)",
    "max_weight": "Weight (kg) (<=)", "other_logic": "Other Logic", "country_hold_cd": "Country Hold Code",
    "global_hold_cd": "Global Hold Code", "sirg_cd": "Requirement group (SIRG)",
}
_COMPARED = [f for f in RULE_FIELDS if f != "ctry_cd"]


# --------------------------------------------------------------------------- #
# catalogue access
# --------------------------------------------------------------------------- #

def current_package(session: Session) -> Optional[str]:
    from tools.core.packages import active_package_version
    return active_package_version(session)


@dataclass
class Catalog:
    package_version: Optional[str]
    groups_by_cd: dict[str, SirgDef]
    groups_by_id: dict[str, SirgDef]
    defs: dict[str, SirDef]
    mapped: set[tuple[str, str]]          # (sirg_id, sir_id) mapped for the country
    mapped_groups: set[str]               # sirg ids mapped for the country
    permitted: dict[str, set[str]]

    @classmethod
    def load(cls, session: Session, country: str) -> "Catalog":
        version = current_package(session)
        groups = list(session.execute(select(SirgDef).where(SirgDef.package_version == version)).scalars())
        defs = {d.id: d for d in session.execute(select(SirDef).where(SirDef.package_version == version)).scalars()}
        rows = session.execute(select(CtryProcMapping.sirg_id, CtryProcMapping.sir_id).where(
            CtryProcMapping.package_version == version, CtryProcMapping.ctry_cd == country)).all()
        permitted = get_reference(session).permitted_values()
        return cls(version, {g.cd: g for g in groups}, {g.id: g for g in groups}, defs,
                   {(a, b) for a, b in rows}, {a for a, _ in rows}, permitted)


# --------------------------------------------------------------------------- #
# row checks
# --------------------------------------------------------------------------- #

def _issue(level: str, field: Optional[str], message: str) -> dict[str, Any]:
    return {"level": level, "field": field, "message": message}


def row_issues(rule: Rule, cat: Catalog, country: str) -> list[dict[str, Any]]:
    """Problems with one Import row and its bindings.

    ``error`` — an authoring mistake; blocks submitting rule config.
    ``package`` — the config package does not (yet) provide what the row needs; fixed by
    Support via the package-coverage request, and gated at the sanity check.
    ``warning`` — worth a look, never blocks.
    """
    out: list[dict[str, Any]] = []
    if rule.ctry_cd != country:
        out.append(_issue("error", "ctry_cd", f"Row is for {rule.ctry_cd}, not {country}."))
    for field, key in (("region", "region"), ("currency", "currency"), ("shipment_type", "shipment_type"),
                       ("value_basis", "value_basis")):
        value = getattr(rule, field)
        allowed = cat.permitted.get(key)
        if value and allowed and value not in allowed:
            out.append(_issue("warning", field, f"'{value}' is not in the workbook's permitted list "
                                                f"({', '.join(sorted(allowed))})."))
    if rule.min_value is not None and rule.max_value is not None and rule.min_value > rule.max_value:
        out.append(_issue("error", "max_value", "Min value is greater than max value."))
    if rule.min_weight is not None and rule.max_weight is not None and rule.min_weight > rule.max_weight:
        out.append(_issue("error", "max_weight", "Min weight is greater than max weight."))
    if (rule.min_value is not None or rule.max_value is not None) and not rule.currency:
        out.append(_issue("error", "currency", "A value band needs a currency."))
    if rule.value_basis and rule.min_value is None and rule.max_value is None:
        out.append(_issue("warning", "value_basis", "Value basis set but no value band — the row applies at any value."))
    if rule.effective_date and rule.expiry_date and rule.expiry_date < rule.effective_date:
        out.append(_issue("error", "expiry_date", "Expiry date is before the effective date."))
    # A TBD hold code makes the Document Reference a placeholder in sirdb, so the row joins no
    # SIR Reference line and raises nothing (docs/adr/0003, parity: IL rows 32/33).
    for field in ("country_hold_cd", "global_hold_cd"):
        if (getattr(rule, field) or "").strip().upper() == "TBD":
            out.append(_issue("error", field, "Hold code is TBD: the Document Reference cannot join a SIR "
                                              "Reference line until the hold code is decided."))
    if rule.other_logic:
        for d in grammar.analyse(rule.other_logic):
            out.append(_issue("error" if d.severity == "error" else "warning", "other_logic", d.message))
    if not rule.sirg_cd:
        out.append(_issue("error", "sirg_cd", "No requirement group (SIRG) — the row would raise nothing."))
    else:
        group = cat.groups_by_cd.get(rule.sirg_cd)
        if group is None:
            out.append(_issue("package", "sirg_cd", f"{rule.sirg_cd} is not in config package {cat.package_version}."))
        elif group.id not in cat.mapped_groups:
            out.append(_issue("package", "sirg_cd", f"{rule.sirg_cd} is not mapped for {country} in the package."))
    if not rule.bindings:
        out.append(_issue("warning", "bindings", "No requirement definition bound (SIR Reference is empty)."))
    for b in rule.bindings:
        label = b.cmpt_nm or b.sir_id or "binding"
        if not b.sir_id:
            out.append(_issue("error", "bindings", f"{label}: no requirement definition id."))
            continue
        if b.sir_id not in cat.defs:
            out.append(_issue("package", "bindings", f"{label}: definition is not shipped by the package."))
        group = cat.groups_by_cd.get(b.sirg_cd or rule.sirg_cd or "")
        if group is not None and (group.id, b.sir_id) not in cat.mapped:
            out.append(_issue("package", "bindings", f"{label}: not mapped to {group.cd} for {country}."))
    if rule.doc_reference and rule.doc_reference != rule.generated_doc_reference:
        out.append(_issue("warning", "doc_reference", f"Document Reference '{rule.doc_reference}' is hand-typed; "
                                                      f"it will be regenerated as '{rule.generated_doc_reference}'."))
    return out


def draft_rows(session: Session, rule_set: RuleSet, country: str) -> list[Rule]:
    return list(session.execute(
        select(Rule).where(Rule.rule_set_id == rule_set.id, Rule.ctry_cd == country)
        .options(selectinload(Rule.bindings)).order_by(Rule.row_no.is_(None), Rule.row_no, Rule.id)).scalars())


def draft_row_errors(session: Session, case: OnboardingCase, rule_set: RuleSet) -> int:
    """How many of the country's draft rows have a blocking row check."""
    cat = Catalog.load(session, case.ctry_cd)
    return sum(1 for r in draft_rows(session, rule_set, case.ctry_cd)
               if any(i["level"] == "error" for i in row_issues(r, cat, case.ctry_cd)))


# --------------------------------------------------------------------------- #
# changes against the workbook baseline
# --------------------------------------------------------------------------- #

def _val(v: Any) -> Any:
    return v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else v


def rule_dict(rule: Rule) -> dict[str, Any]:
    return {f: _val(getattr(rule, f)) for f in RULE_FIELDS}


def _bindings_key(rule: Rule) -> list[tuple]:
    return sorted((b.sir_id or "", b.sirg_cd or "", bool(b.waived_to_validate), bool(b.waived_if_whitelisted),
                   b.check_service_code or "", tuple(sorted(b.attribute_ids or []))) for b in rule.bindings)


def changes(session: Session, draft: RuleSet, baseline: Sequence[Any], country: str) -> list[dict[str, Any]]:
    """Draft rows vs the country's baseline reference rows. Matching is by workbook row number.

    ``baseline`` is ``get_reference(session).baseline_rules(country)`` (any objects with
    the ``Rule`` attribute names).
    """
    draft_rules = list(session.execute(select(Rule).where(Rule.rule_set_id == draft.id, Rule.ctry_cd == country)
                                       .options(selectinload(Rule.bindings)).order_by(Rule.row_no)).scalars())
    base = {r.row_no: r for r in baseline if r.row_no is not None and r.ctry_cd == country}
    out = []
    seen: set[int] = set()
    for r in draft_rules:
        old = base.get(r.row_no) if r.row_no is not None else None
        if old is None:
            out.append({"rule_id": r.id, "row_no": r.row_no, "status": "NEW", "row": rule_dict(r), "fields": {}})
            continue
        seen.add(r.row_no)
        fields = {f: {"from": _val(getattr(old, f)), "to": _val(getattr(r, f))}
                  for f in _COMPARED if getattr(old, f) != getattr(r, f)}
        if _bindings_key(old) != _bindings_key(r):
            fields["bindings"] = {"from": f"{len(old.bindings)} binding(s)", "to": f"{len(r.bindings)} binding(s)"}
        out.append({"rule_id": r.id, "row_no": r.row_no, "status": "CHANGED" if fields else "UNCHANGED",
                    "row": rule_dict(r), "fields": fields})
    for row_no, old in base.items():
        if row_no not in seen:
            out.append({"rule_id": None, "row_no": row_no, "status": "REMOVED", "row": rule_dict(old), "fields": {}})
    order = {"NEW": 0, "CHANGED": 1, "REMOVED": 2, "UNCHANGED": 3}
    return sorted(out, key=lambda c: (order[c["status"]], c["row_no"] or 0))


# --------------------------------------------------------------------------- #
# package coverage (Technical SIR / Technical SIRG)
# --------------------------------------------------------------------------- #

def coverage(session: Session, rules: list[Rule], cat: Catalog, country: str) -> dict[str, Any]:
    """Every (group, definition) the draft needs, and whether the package provides it."""
    reference = get_reference(session)
    mirror_sirg = {m.sirg_cd: m for m in reference.mirror_sirg(country)}
    mirror_sir = {m.sir_id: m for m in reference.mirror_sir()}
    needed: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rules:
        for b in (r.bindings or [None]):
            cd = (b.sirg_cd if b else None) or r.sirg_cd or ""
            sir_id = (b.sir_id if b else None) or ""
            key = (cd, sir_id)
            if key in needed or not cd:
                continue
            group = cat.groups_by_cd.get(cd)
            sir = cat.defs.get(sir_id) if sir_id else None
            mirror = mirror_sir.get(sir_id) if sir_id else None
            needed[key] = {
                "sirg_cd": cd,
                "sirg_id": group.id if group else (mirror_sirg[cd].sirg_id if cd in mirror_sirg else None),
                "sirg_in_package": group is not None,
                "sir_id": sir_id or None,
                "cmpt_nm": (sir.cmpt_nm if sir else None) or (b.cmpt_nm if b else None)
                or (mirror.cmpt_nm if mirror else None),
                "sir_name": (sir.nm if sir else None) or (mirror.nm if mirror else None),
                "sir_in_package": bool(sir),
                "mapped_for_country": bool(group and sir_id and (group.id, sir_id) in cat.mapped),
                "group_mapped_for_country": bool(group and group.id in cat.mapped_groups),
            }
    items = list(needed.values())
    for i in items:
        i["ok"] = i["sirg_in_package"] and (i["sir_id"] is None or (i["sir_in_package"] and i["mapped_for_country"]))
    request = [i for i in items if not i["ok"]]
    return {"package_version": cat.package_version, "items": items, "complete": not request,
            "support_request": [{
                "CtryProc.DhlCtryCd": country, "CtryProc.ProcLvlCd": DEFAULT_PROC_LVL,
                "ShpInfReqGrpDef.Cd": i["sirg_cd"], "ShpInfReqGrpDef.Id": i["sirg_id"] or "",
                "ShpInfReqDef.Id": i["sir_id"] or "", "ShpInfReqDef.CmptNm": i["cmpt_nm"] or "",
                "Needed": "; ".join(n for n, bad in (
                    ("SIRG in catalogue", not i["sirg_in_package"]),
                    ("SIR definition shipped", bool(i["sir_id"]) and not i["sir_in_package"]),
                    ("country mapping", bool(i["sir_id"]) and not i["mapped_for_country"])) if bad),
            } for i in request]}


# --------------------------------------------------------------------------- #
# condition builder (Other Logic)
# --------------------------------------------------------------------------- #

BUILDER_TYPES: dict[str, dict[str, Any]] = {
    "service_code": {"label": "Service code", "ops": ["has any of", "has none of"], "values": "codes, e.g. DD, DS"},
    "incoterm": {"label": "Incoterm", "ops": ["is one of", "is none of"], "values": "e.g. DDP"},
    "origin_country": {"label": "Origin country", "ops": ["is one of", "is none of"], "values": "ISO-2, e.g. CN, US"},
    "destination_service_area": {"label": "Destination service area", "ops": ["is one of"], "values": "e.g. AUH"},
    "short_code": {"label": "Short code (e.g. SDT)", "ops": ["is present (has a value)", "is blank"],
                   "values": "one short code, e.g. SDT"},
    "hs_code": {"label": "Inbound HS code", "ops": ["is blank", "equals"], "values": "HS code (for equals)"},
}


def _values(raw: Any) -> list[str]:
    if isinstance(raw, list):
        items = raw
    else:
        items = str(raw or "").replace(";", ",").split(",")
    return [str(v).strip().upper() for v in items if str(v).strip()]


def _clause(c: dict[str, Any]) -> str:
    kind, op, vals = c.get("type"), str(c.get("op") or ""), _values(c.get("values"))
    negative = "none" in op
    if kind in ("service_code", "incoterm", "destination_service_area"):
        target = {"service_code": "serviceCodeList", "incoterm": "incotermCodeList",
                  "destination_service_area": "destinationServiceArea"}[kind]
        if not vals:
            raise ValueError(f"{BUILDER_TYPES[kind]['label']}: give at least one value.")
        if negative:
            return " && ".join(f'!{target}.contains("{v}")' for v in vals)
        return " || ".join(f'{target}.contains("{v}")' for v in vals)
    if kind == "origin_country":
        if not vals:
            raise ValueError("Origin country: give at least one country code.")
        if negative:
            return " && ".join(f'OriginCountry!="{v}"' for v in vals)
        return " || ".join(f'OriginCountry=="{v}"' for v in vals)
    if kind == "short_code":
        if len(vals) != 1:
            raise ValueError("Short code: give exactly one code, e.g. SDT.")
        cmp_ = "==" if "blank" in op else "!="
        return f'matchCiMask("shortCode|==|{vals[0]}","value|{cmp_}|<blank>")'
    if kind == "hs_code":
        if "blank" in op:
            return 'hscode("inboundHsCode","<blank>")'
        if len(vals) != 1:
            raise ValueError("HS code: give one value to compare.")
        return f'hscode("inboundHsCode","{vals[0]}")'
    if kind == "raw":
        text = str(c.get("values") or "").strip()
        if not text:
            raise ValueError("Custom expression is empty.")
        return text
    raise ValueError(f"Unknown condition type: {kind}")


def build_expression(clauses: list[dict[str, Any]], joiner: str = "and") -> dict[str, Any]:
    """Compose Other Logic from builder clauses and check it with the platform grammar."""
    if not clauses:
        return {"expression": "", "parses": True, "errors": [], "warnings": []}
    op = " && " if joiner == "and" else " || "
    parts = []
    for c in clauses:
        text = _clause(c)
        multi = (" && " in text or " || " in text) and len(clauses) > 1
        parts.append(f"({text})" if multi else text)
    expression = op.join(parts)
    diags = grammar.analyse(expression)
    return {"expression": expression,
            "parses": not any(d.code == "EXPR_PARSE" for d in diags),
            "errors": [d.message for d in diags if d.severity == "error"],
            "warnings": [d.message for d in diags if d.severity == "warning"]}


def palette(session: Session) -> list[dict[str, Any]]:
    """The workbook's Other Logic palette, each entry checked (some palette entries are wrong)."""
    out = []
    for expr in dict.fromkeys(get_reference(session).expression_templates()):
        diags = grammar.analyse(expr)
        out.append({"expression": expr, "ok": not any(d.severity == "error" for d in diags),
                    "problems": [d.message for d in diags if d.severity == "error"]})
    return out


# --------------------------------------------------------------------------- #
# M2C workbook generation
# --------------------------------------------------------------------------- #

def _fmt_date(d: Optional[dt.date]) -> str:
    return d.strftime("%d-%m-%Y") if d else ""


def build_m2c_workbook(session: Session, case: OnboardingCase, draft: RuleSet,
                       change_rows: list[dict[str, Any]]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    country = case.ctry_cd
    rules = list(session.execute(select(Rule).where(Rule.rule_set_id == draft.id, Rule.ctry_cd == country)
                                 .options(selectinload(Rule.bindings)).order_by(Rule.row_no.is_(None), Rule.row_no)
                                 ).scalars())
    cat = Catalog.load(session, country)
    wb = Workbook()

    def sheet(title: str, headers: list[str], first: bool = False):
        ws = wb.active if first else wb.create_sheet(title)
        ws.title = title
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="D40511")
        for i, h in enumerate(headers, start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = max(14, min(48, len(h) + 4))
        return ws

    # Import — Document Reference is the workbook's CONCATENATE formula, never typed.
    imp = sheet("Import", WORKBOOK_IMPORT_HEADERS, first=True)
    row_of: dict[str, int] = {}
    for r in rules:
        n = imp.max_row + 1
        row_of[r.id] = n
        imp.append([r.region or "", r.ctry_cd, r.shipment_type or "", _fmt_date(r.effective_date),
                    _fmt_date(r.expiry_date), r.network_product_codes or "", r.value_basis or "", r.currency or "",
                    r.min_value, r.max_value, r.min_weight, r.max_weight, r.other_logic or "",
                    r.country_hold_cd or "", r.global_hold_cd or "",
                    f'=CONCATENATE(B{n},"|Import|",N{n},"|",O{n})',
                    f"{r.ctry_cd}|Import|{r.sirg_cd or ''}"])
    sheet("Export", WORKBOOK_IMPORT_HEADERS + ["Business Owner"])

    # SIR Reference — each binding points at its own Import row (positions generated, so always right).
    ref = sheet("SIR Reference", SIR_REFERENCE_HEADERS)
    used_sir: dict[str, Rule] = {}
    for r in rules:
        n = row_of[r.id]
        for b in r.bindings:
            # SIR Document Reference is Country|Import|SIRGCd|CmptNm (4 parts), verified on the workbook.
            ref.append([f'=IF(Import!P{n}<>0,Import!P{n},"")',
                        f"{r.ctry_cd}|Import|{b.sirg_cd or r.sirg_cd or ''}|{b.cmpt_nm or ''}",
                        "Y" if b.waived_if_whitelisted else "N", "Y" if b.waived_to_validate else "N",
                        b.check_service_code or "", b.cmpt_nm or "", b.sir_id or "",
                        "&".join(b.attribute_ids or [])])
            if b.sir_id:
                used_sir[b.sir_id] = r

    tsir = sheet("Technical SIR", ["CmptNm", "Nm", "Dsc", "SIR Technical ID"])
    tsirg = sheet("Technical SIRG", ["SIRG Technical ID", "SIRG Cd", "SIRG Nm", "SIRG Dsc", "DHL Ctry Cd",
                                     "Processing Type", "CmptNm", "SIR Technical ID"])
    for sir_id, r in used_sir.items():
        d = cat.defs.get(sir_id)
        tsir.append([d.cmpt_nm if d else "", d.nm if d else "(not in package)", d.dsc if d else "", sir_id])
        g = cat.groups_by_cd.get(r.sirg_cd or "")
        tsirg.append([g.id if g else "", r.sirg_cd or "", g.nm if g else "(not in package)", g.dsc if g else "",
                      country, DEFAULT_PROC_LVL, d.cmpt_nm if d else "", sir_id])

    pal = sheet("Other Logic", ["Other Logic"])
    for p in palette(session):
        pal.append([p["expression"]])

    lists = {k: sorted(v) for k, v in cat.permitted.items()}
    val = sheet("Validation", [k.replace("_", " ").title() for k in lists])
    for i in range(max((len(v) for v in lists.values()), default=0)):
        val.append([v[i] if i < len(v) else None for v in lists.values()])

    log = sheet("Changes (platform)", ["Status", "Workbook row", "Field", "From", "To"])
    for c in change_rows:
        if c["status"] == "UNCHANGED":
            continue
        if c["fields"]:
            for f, ch in c["fields"].items():
                log.append([c["status"], c["row_no"], RULE_FIELDS.get(f, f), str(ch["from"]), str(ch["to"])])
        else:
            log.append([c["status"], c["row_no"], "(whole row)", "", ""])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
