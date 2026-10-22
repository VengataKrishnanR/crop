"""The sanity check — six plain-language checks before UAT preparation.

Each check answers one question the CCRE team would otherwise work out by hand,
says exactly which rows are involved, and how to fix it:

1. rows               Are the M2C rows complete?            (row checks, per row)
2. requirement_match  Do the rows match the approved requirement?   (field by field)
3. rules              Do the rules pass validation?          (the 16 checks, package checks excluded)
4. package            Can the config package raise every requirement?   (Technical SIR/SIRG)
5. dmg                Is the DMG email task completed?
6. changes            What changes in the M2C?               (information for the reviewer)

``package`` and ``requirement_match`` may be **waived** with a reason (e.g. the
Support ticket for a package rebuild, or "split into two rows on purpose").
Everything else must be fixed.

A run is saved (``SanityRun``) with a fingerprint of exactly what was checked;
approving the sanity check needs a passing run whose fingerprint still matches.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from tools import ruleconfig as rc
from tools.core import grammar
from tools.core.models import OnboardingCase, Rule, SanityRun, SanityWaiver

WAIVABLE = {"package", "requirement_match"}
PACKAGE_CODES = {"CHK002", "CHK003", "CHK015"}

TITLES = {
    "rows": "The M2C rows are complete",
    "requirement_match": "The M2C rows match the approved requirement",
    "rules": "The rules pass validation",
    "package": "The config package can raise every requirement",
    "dmg": "The DMG email task is completed",
    "changes": "What changes in the M2C",
}
WHY = {
    "rows": "A row with an error (e.g. min above max, expiry before effective date, no requirement group) "
            "cannot be loaded or behaves differently from what was agreed.",
    "requirement_match": "Test cases are written from the requirement; if the M2C says something else, "
                         "UAT fails for the wrong reason.",
    "rules": "The deterministic checks catch broken expressions, values outside the permitted lists, "
             "bindings that do not resolve and duplicate rows.",
    "package": "CCRE can only raise a requirement the config package ships and maps for the country.",
    "dmg": "The shipment data must reach CCRE; the DMG team configures that from the DMG email.",
    "changes": "The reviewer sees exactly what the onboarding changes in the M2C.",
}
FIX = {
    "rows": {"label": "Send back to rule config to fix the rows", "action": "send_back"},
    "requirement_match": {"label": "Send back to rule config to align the rows", "action": "send_back"},
    "rules": {"label": "Send back to rule config to fix the rules", "action": "send_back"},
    "package": {"label": "Download the package request for Support", "action": "package_request"},
    "dmg": {"label": "Send back to rule config to complete the DMG email", "action": "send_back"},
}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def active_waivers(session: Session, case_id: str) -> dict[str, SanityWaiver]:
    rows = session.execute(select(SanityWaiver).where(SanityWaiver.case_id == case_id,
                                                      SanityWaiver.revoked_at.is_(None))
                           .order_by(SanityWaiver.created_at)).scalars()
    return {w.item_key: w for w in rows}


def _date(v: Any) -> Optional[str]:
    return v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else (v or None)


def _num(v: Any) -> Optional[float]:
    return None if v is None else round(float(v), 4)


def _codes(v: Any) -> list[str]:
    if isinstance(v, list):
        return sorted(x.strip().upper() for x in v if str(x).strip())
    return sorted(x.strip().upper() for x in str(v or "").split(",") if x.strip())


def _logic(v: Optional[str]) -> str:
    if not v:
        return ""
    try:
        return grammar.normalise(v)
    except Exception:          # plain words — compare as written
        return " ".join(v.split())


_MATCH_FIELDS = [
    ("region", "Region", lambda x: x or None),
    ("shipment_type", "B2B/B2C", lambda x: x or None),
    ("effective_date", "Effective date", _date),
    ("expiry_date", "Date of expiry", _date),
    ("network_product_codes", "Network product codes", _codes),
    ("value_basis", "DV/IV", lambda x: x or None),
    ("currency", "Currency", lambda x: x or None),
    ("min_value", "Min value", _num),
    ("max_value", "Max value", _num),
    ("min_weight", "Min weight", _num),
    ("max_weight", "Max weight", _num),
    ("other_logic", "Other Logic", _logic),
]


def _diff(rule: Rule, want: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key, label, norm in _MATCH_FIELDS:
        a, b = norm(want.get(key)), norm(getattr(rule, key))
        if a != b:
            out.append({"field": label, "requirement": want.get(key), "m2c": _date(getattr(rule, key))
                        if key.endswith("_date") else getattr(rule, key)})
    return out


# --------------------------------------------------------------------------- #
# the checks
# --------------------------------------------------------------------------- #

def evaluate(session: Session, case: OnboardingCase) -> dict[str, Any]:
    """The checklist as it stands now (nothing is saved)."""
    from tools.validation import validate_rule_set
    from tools.workflow.case_facts import case_rule_set, latest_dmg_task, latest_requirement

    country = case.ctry_cd
    rs = case_rule_set(session, case)
    rules = rc.draft_rows(session, rs, country) if rs else []
    cat = rc.Catalog.load(session, country)
    waivers = active_waivers(session, case.id)
    items: list[dict[str, Any]] = []

    def add(key: str, ok: bool, summary: str, findings: Optional[list] = None, notes: Optional[list] = None,
            info: bool = False) -> None:
        status = "info" if info else ("pass" if ok else ("waived" if key in waivers else "fail"))
        w = waivers.get(key)
        items.append({
            "key": key, "title": TITLES[key], "why": WHY[key], "status": status, "summary": summary,
            "findings": findings or [], "notes": notes or [],
            "fix": None if ok or info else FIX.get(key), "waivable": key in WAIVABLE and not ok and not info,
            "waiver": {"id": w.id, "reason": w.reason, "reference": w.reference, "by": w.waived_by,
                       "at": w.created_at.isoformat()} if w and not ok else None,
        })

    # 1. rows complete
    if not rules:
        add("rows", False, "The M2C draft has no rows for this country." if rs else "The M2C draft was not started.")
    else:
        bad = []
        for r in rules:
            errs = [i["message"] for i in rc.row_issues(r, cat, country) if i["level"] == "error"]
            if errs:
                bad.append({"row": r.row_no or "new", "group": r.sirg_cd, "problems": errs})
        add("rows", not bad, f"All {len(rules)} row(s) are complete." if not bad
            else f"{len(bad)} of {len(rules)} row(s) have errors.", bad)

    # 2. matches the requirement
    req = latest_requirement(session, case.id)
    want = ((req.structured or {}).get("m2c_row") if req else None) or None
    groups = ((req.structured or {}).get("m2c") or {}).get("requirement_groups") if req else None
    groups = groups or ((req.structured or {}).get("requirement_groups") if req else None) or []
    if not want:
        add("requirement_match", True, "The requirement has no M2C criteria to compare (captured before the "
                                       "M2C intake) — compare by reading it.", info=True)
    else:
        findings = []
        for g in groups:
            candidates = [r for r in rules if (r.sirg_cd or "") == g]
            if not candidates:
                findings.append({"group": g, "row": None, "differences": [],
                                 "problem": f"No M2C row raises {g}."})
                continue
            best = min(candidates, key=lambda r: len(_diff(r, want)))
            diffs = _diff(best, want)
            if diffs:
                findings.append({"group": g, "row": best.row_no or "new", "differences": diffs,
                                 "problem": f"Row {best.row_no or '(new)'} for {g} differs from the requirement "
                                            f"in {len(diffs)} field(s)."})
        add("requirement_match", not findings,
            f"Every requirement group ({', '.join(groups) or '—'}) has a row that matches the requirement."
            if not findings else f"{len(findings)} requirement group(s) do not match.", findings)

    # 3 + 4. validation, split into rule problems and package gaps
    report = validate_rule_set(session, rs.id, case_id=case.id, persist=False)[0] if rs else None
    rule_blockers = [f for f in (report.blockers if report else []) if f.code not in PACKAGE_CODES]
    pkg_blockers = [f for f in (report.blockers if report else []) if f.code in PACKAGE_CODES]
    cautions = [f for f in (report.cautions if report else []) if f.code not in PACKAGE_CODES]
    # Findings name rows by their id; people know them by row number.
    names = {r.id: f"row {r.row_no}" if r.row_no else f"new {r.sirg_cd or ''} row".replace("  ", " ") for r in rules}
    for b in (r.bindings for r in rules):
        for x in b:
            names[x.id] = f"{names.get(x.rule_id, 'row')} binding {x.cmpt_nm or ''}".strip()
    readable = lambda subjects: [names.get(s, s) for s in subjects[:10]]  # noqa: E731
    add("rules", bool(report) and not rule_blockers,
        (f"{len(report.checks_run)} checks passed" + (f" ({len(cautions)} note(s) to read)." if cautions else ".")
         if report and not rule_blockers else f"{len(rule_blockers)} blocking finding(s)." if report
         else "Nothing to validate yet."),
        [{"check": f.code, "where": f.where, "message": f.message, "rows": readable(f.subjects)} for f in rule_blockers],
        [{"check": f.code, "message": f.message} for f in cautions[:10]])

    cov = rc.coverage(session, rules, cat, country) if rules else {"complete": False, "support_request": []}
    gaps = cov["support_request"]
    pkg_ok = bool(rules) and not gaps and not pkg_blockers
    add("package", pkg_ok,
        f"Package {cat.package_version} maps every group and definition for {country}." if pkg_ok
        else f"{len(gaps) or len(pkg_blockers)} mapping(s) missing from package {cat.package_version} — "
             "Support must add them.",
        [{"group": g["ShpInfReqGrpDef.Cd"], "definition": g["ShpInfReqDef.CmptNm"] or g["ShpInfReqDef.Id"] or "—",
          "needed": g["Needed"]} for g in gaps]
        or [{"group": "", "definition": f.where, "needed": f.message} for f in pkg_blockers])

    # 5. DMG
    dmg = latest_dmg_task(session, case.id)
    done = dmg is not None and dmg.status in ("SENT", "NOT_REQUIRED")
    add("dmg", done, {None: "The DMG email has not been prepared.", "DRAFT": "The DMG email is still a draft.",
                      "IN_REVIEW": "The DMG email is waiting for CCRE review.",
                      "SENT": f"Approved by {dmg.decided_by if dmg else ''} and sent"
                              f"{' on ' + dmg.sent_at.strftime('%d-%m-%Y') if dmg and dmg.sent_at else ''}.",
                      "NOT_REQUIRED": f"Not required: {dmg.decision_comment if dmg else ''}"}[dmg.status if dmg else None])

    # 6. changes (information)
    if rs:
        from tools.reference import get_reference
        ch = rc.changes(session, rs, get_reference(session).baseline_rules(country), country)
        counts = {s: sum(1 for c in ch if c["status"] == s) for s in ("NEW", "CHANGED", "REMOVED", "UNCHANGED")}
        add("changes", True, f"{counts['NEW']} new, {counts['CHANGED']} changed, {counts['REMOVED']} removed, "
                             f"{counts['UNCHANGED']} unchanged row(s) compared with the workbook.",
            [{"status": c["status"].lower(), "row": c["row_no"] or "new", "group": c["row"].get("sirg_cd"),
              "fields": {rc.RULE_FIELDS.get(k, k): v for k, v in c["fields"].items()}}
             for c in ch if c["status"] != "UNCHANGED"], info=True)

    blocking = [i for i in items if i["status"] == "fail"]
    return {
        "ready": not blocking,
        "items": items,
        "counts": {s: sum(1 for i in items if i["status"] == s) for s in ("pass", "fail", "waived", "info")},
        "fingerprint": fingerprint(session, case, rules, req, dmg, cat.package_version, waivers),
        "send_back_reason": "\n".join(_reason_line(i) for i in blocking),
    }


def _reason_line(item: dict[str, Any]) -> str:
    """One line per failing check that tells rule config exactly what to change."""
    f = item.get("findings") or []
    key = item["key"]
    if key == "requirement_match":
        detail = "; ".join(
            (f"row {x['row']} ({x['group']}) differs in " + ", ".join(d["field"] for d in x["differences"]))
            if x["differences"] else x["problem"] for x in f)
    elif key == "rows":
        detail = "; ".join(f"row {x['row']}: " + ", ".join(x["problems"]) for x in f)
    elif key == "rules":
        detail = "; ".join(f"{x['check']} {x['message']}" + (f" ({', '.join(x['rows'])})" if x.get("rows") else "")
                           for x in f)
    elif key == "package":
        detail = "; ".join(f"{x['group']} {x['definition']}: {x['needed']}".strip() for x in f)
    else:
        detail = ""
    return f"- {item['title']}: {detail or item['summary']}"


def fingerprint(session: Session, case: OnboardingCase, rules: list[Rule], req: Any, dmg: Any,
                package_version: Optional[str], waivers: dict[str, SanityWaiver]) -> str:
    payload = {
        "rows": sorted([json.dumps({**rc.rule_dict(r), "b": rc._bindings_key(r)}, sort_keys=True, default=str)
                        for r in rules]),
        "requirement": [req.id, req.version] if req else None,
        "dmg": dmg.status if dmg else None,
        "package": package_version,
        "waivers": sorted(w.id for w in waivers.values()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# runs
# --------------------------------------------------------------------------- #

def run(session: Session, case: OnboardingCase, actor: str) -> SanityRun:
    """Evaluate and save the run as evidence."""
    from tools.workflow.case_facts import case_rule_set, correction_cycle

    ev = evaluate(session, case)
    rs = case_rule_set(session, case)
    r = SanityRun(case_id=case.id, rule_set_id=rs.id if rs else None, cycle=correction_cycle(session, case.id),
                  fingerprint=ev["fingerprint"], status="PASS" if ev["ready"] else "FAIL",
                  passed=ev["counts"]["pass"], failed=ev["counts"]["fail"], waived=ev["counts"]["waived"],
                  items=ev["items"], run_by=actor)
    session.add(r)
    session.flush()
    return r


def latest_run(session: Session, case_id: str) -> Optional[SanityRun]:
    return session.execute(select(SanityRun).where(SanityRun.case_id == case_id)
                           .order_by(SanityRun.created_at.desc()).limit(1)).scalar_one_or_none()


def approval_gap(session: Session, case: OnboardingCase) -> Optional[str]:
    """Why the sanity check cannot be approved yet, or None."""
    last = latest_run(session, case.id)
    if last is None:
        return "Run the sanity check first."
    if last.status != "PASS":
        return f"The last sanity check run failed ({last.failed} check(s)) — fix them or send back to rule config."
    now = evaluate(session, case)["fingerprint"]
    if now != last.fingerprint:
        return "The configuration changed after the last sanity check run — run it again."
    return None
