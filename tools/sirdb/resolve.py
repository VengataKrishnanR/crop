"""Phase 4 — reference resolution, rule validation and the final Import dataset.

Resolution path (documented in docs/sirdb/02_design.md):

    business choice (country, SIRG code, processing type IMP_CLR)
      → Technical SIRG   (dhl_ctry_cd, processing_type, sirg_cd)      0 / 1 / many
      → component + SIR technical id
      → Technical SIR    (sir_technical_id, cmpt_nm) must exist
      → SIR Reference    lines for that country + SIRG code (attributes, waivers, service code)

Zero, one and several matches are always reported as such — never "take the first".
Missing catalog entries are reported as reference-data maintenance; nothing here
creates SIR/SIRG catalog rows from business input.

``Other Logic`` is text: it is stored and compared, never executed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import psycopg

from .db import connect
from .profile import PLACEHOLDER, parse_dmy

PROC = "IMP_CLR"
IMPORT_HEADERS = [
    "Region", "Country", "B2B/B2C", "Effective Date (DD-MM-YYY)", "Date of Expiry (DD-MM-YYY)",
    "Network Product Code", "Declared Value/ Intristic Value", "Currency", "Min Value (>=)", "Max Value (<=)",
    "Shipt Weight (kg) (>=)", "Shipt Weight (kg) (<=)", "Other Logic", "Country Hold Code", "Global Hold Code",
    "Document Reference", "SIRG Document Reference",
]


class ResolveError(Exception):
    pass


def current_batch(cur) -> int:
    cur.execute("SELECT batch_id FROM sirdb.import_batch WHERE is_current")
    row = cur.fetchone()
    if not row:
        raise ResolveError("No current batch — load a workbook first.")
    return row[0]


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #

@dataclass
class SirgResolution:
    status: str                       # RESOLVED | NOT_FOUND | AMBIGUOUS | DUPLICATE_RECORDS
    country: str
    processing_type: str
    sirg_cd: str
    matches: list[dict[str, Any]] = field(default_factory=list)
    sirg_technical_id: Optional[str] = None
    sirg_nm: Optional[str] = None
    cmpt_nm: Optional[str] = None
    sir_technical_id: Optional[str] = None
    sir_in_catalog: Optional[bool] = None
    sir_catalog_cmpt_nm: Optional[str] = None
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_sirg(cur, country: str, sirg_cd: str, processing_type: str = PROC,
                 batch_id: Optional[int] = None) -> SirgResolution:
    bid = batch_id or current_batch(cur)
    cur.execute("""SELECT source_row_no, sirg_technical_id, sirg_nm, cmpt_nm, sir_technical_id
                   FROM sirdb.technical_sirg
                   WHERE batch_id = %s AND dhl_ctry_cd = %s AND processing_type = %s AND sirg_cd = %s
                   ORDER BY source_row_no""", (bid, country, processing_type, sirg_cd))
    rows = [dict(zip(("source_row", "sirg_technical_id", "sirg_nm", "cmpt_nm", "sir_technical_id"), r))
            for r in cur.fetchall()]
    res = SirgResolution("NOT_FOUND", country, processing_type, sirg_cd, rows)
    if not rows:
        res.message = (f"No Technical SIRG mapping for {country} · {processing_type} · {sirg_cd}. "
                       "Reference-data maintenance is needed (the mapping is not created from business input).")
        return res
    targets = {(r["sirg_technical_id"], r["cmpt_nm"], r["sir_technical_id"]) for r in rows}
    if len(targets) > 1:
        res.status = "AMBIGUOUS"
        res.message = f"{len(rows)} Technical SIRG rows match with {len(targets)} different targets " \
                      f"(rows {[r['source_row'] for r in rows]}). A person must decide which applies."
        return res
    res.status = "RESOLVED" if len(rows) == 1 else "DUPLICATE_RECORDS"
    if len(rows) > 1:
        res.message = f"{len(rows)} identical Technical SIRG records (rows {[r['source_row'] for r in rows]})."
    res.sirg_technical_id, res.cmpt_nm, res.sir_technical_id = next(iter(targets))
    res.sirg_nm = rows[0]["sirg_nm"]
    cur.execute("SELECT cmpt_nm FROM sirdb.technical_sir WHERE batch_id = %s AND sir_technical_id = %s",
                (bid, res.sir_technical_id))
    hit = cur.fetchone()
    res.sir_in_catalog = bool(hit) and hit[0] == res.cmpt_nm
    res.sir_catalog_cmpt_nm = hit[0] if hit else None
    return res


def sir_reference_lines(cur, country: str, sirg_cd: str, document_reference: Optional[str] = None,
                        batch_id: Optional[int] = None) -> list[dict[str, Any]]:
    """SIR Reference lines for a rule. Joins on the SIR Document Reference (country + SIRG code) and,
    when a non-placeholder Document Reference is given, on that as well. Each line says how it matched."""
    bid = batch_id or current_batch(cur)
    use_doc = bool(document_reference) and not PLACEHOLDER.search(document_reference or "")
    cur.execute("""
        SELECT s.source_row_no, s.document_reference, s.sir_document_reference, s.cmpt_nm, s.sir_technical_id,
               s.waived_if_whitelisted_raw, s.waived_if_whitelisted, s.waived_to_validate_raw, s.waived_to_validate,
               s.check_if_service_code, s.attribute_id_raw, s.col_09_unheaded,
               (NOT s.is_sdr_placeholder AND s.sdr_country = %(c)s AND s.sdr_sirg_cd = %(g)s) AS by_sirg,
               (%(use_doc)s AND s.document_reference = %(d)s)                                   AS by_docref,
               coalesce((SELECT json_agg(json_build_object('position', a.position, 'attribute_id', a.attribute_id,
                                                           'col_09_entry', a.col_09_entry) ORDER BY a.position)
                         FROM sirdb.sir_reference_attribute a
                         WHERE a.batch_id = s.batch_id AND a.source_row_no = s.source_row_no), '[]'::json)
        FROM sirdb.sir_reference s
        WHERE s.batch_id = %(b)s
          AND ((NOT s.is_sdr_placeholder AND s.sdr_country = %(c)s AND s.sdr_sirg_cd = %(g)s)
               OR (%(use_doc)s AND s.document_reference = %(d)s))
        ORDER BY s.source_row_no""",
                {"b": bid, "c": country, "g": sirg_cd, "d": document_reference, "use_doc": use_doc})
    cols = ["source_row", "document_reference", "sir_document_reference", "cmpt_nm", "sir_technical_id",
            "waived_if_whitelisted_raw", "waived_if_whitelisted", "waived_to_validate_raw", "waived_to_validate",
            "check_if_service_code", "attribute_id_raw", "col_09_unheaded", "by_sirg", "by_docref", "attributes"]
    out = []
    for r in cur.fetchall():
        d = dict(zip(cols, r))
        d["join"] = "+".join(x for x, on in (("SIRG_DOCUMENT_REFERENCE", d.pop("by_sirg")),
                                            ("DOCUMENT_REFERENCE", d.pop("by_docref"))) if on)
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# validating a proposed rule
# --------------------------------------------------------------------------- #

def _list(cur, bid: int, name: str) -> set[str]:
    cur.execute("""SELECT i.value_normalized FROM sirdb.reference_list_item i JOIN sirdb.reference_list l USING (list_id)
                   WHERE l.batch_id = %s AND l.list_name = %s""", (bid, name))
    return {r[0] for r in cur.fetchall()}


def _date(v: Any) -> tuple[Optional[dt.date], Optional[str]]:
    if v in (None, ""):
        return None, None
    if isinstance(v, dt.date):
        return v, None
    s = str(v)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        try:
            return dt.date.fromisoformat(s), None
        except ValueError:
            return None, "not a valid date"
    return parse_dmy(s)


def _number(v: Any) -> tuple[Optional[Decimal], Optional[str]]:
    if v in (None, ""):
        return None, None
    try:
        return Decimal(str(v)), None
    except Exception:
        return None, "not a number"


def validate_rule(cur, rule: dict[str, Any], batch_id: Optional[int] = None) -> dict[str, Any]:
    """Blocking errors vs non-blocking warnings for a proposed Import rule, each with its reason."""
    bid = batch_id or current_batch(cur)
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    err = lambda f, m: errors.append({"field": f, "message": m})       # noqa: E731
    warn = lambda f, m: warnings.append({"field": f, "message": m})    # noqa: E731

    for f, v in rule.items():
        if isinstance(v, str) and PLACEHOLDER.search(v):
            err(f, f"'{v}' is a placeholder (TEST/TBD); a real value is needed.")

    country = (rule.get("country") or "").strip()
    if not re.fullmatch(r"[A-Z]{2}", country):
        err("country", "Country must be an ISO two-letter code, e.g. DE.")
    sirg_cd = (rule.get("sirg_cd") or "").strip()
    proc = rule.get("processing_type") or PROC
    has_holds = bool(rule.get("country_hold_code") or rule.get("global_hold_code"))
    if not sirg_cd and not has_holds:
        err("sirg_cd", "Give the requirement group (SIRG code) — or hold codes for a hold-code rule.")

    resolution = None
    lines: list[dict[str, Any]] = []
    if sirg_cd and country:
        resolution = resolve_sirg(cur, country, sirg_cd, proc, bid)
        if resolution.status == "NOT_FOUND":
            err("sirg_cd", resolution.message)
        elif resolution.status == "AMBIGUOUS":
            err("sirg_cd", resolution.message)
        elif resolution.status == "DUPLICATE_RECORDS":
            warn("sirg_cd", resolution.message)
        if resolution.status in ("RESOLVED", "DUPLICATE_RECORDS") and not resolution.sir_in_catalog:
            err("sirg_cd", f"SIR {resolution.sir_technical_id} / {resolution.cmpt_nm} is not in Technical SIR "
                           f"(catalog says {resolution.sir_catalog_cmpt_nm}).")
        lines = sir_reference_lines(cur, country, sirg_cd, rule.get("document_reference"), bid)
        if resolution.status in ("RESOLVED", "DUPLICATE_RECORDS") and not lines:
            warn("sir_reference", f"No SIR Reference line for {country}|Import|{sirg_cd}: the whole definition is "
                                  "requested, with no attribute, waiver or service-code settings.")
        other_cmpt = [l for l in lines if l["cmpt_nm"] and resolution and resolution.cmpt_nm
                      and l["cmpt_nm"] != resolution.cmpt_nm and "SIRG" in l["join"]]
        if other_cmpt:
            warn("sir_reference", f"{len(other_cmpt)} SIR Reference line(s) name another component than "
                                  f"{resolution.cmpt_nm}.")

    eff, e1 = _date(rule.get("effective_date"))
    exp, e2 = _date(rule.get("expiry_date"))
    if e1:
        err("effective_date", f"Effective date: {e1}.")
    elif eff is None:
        err("effective_date", "An effective date is required (approved business input).")
    if e2:
        err("expiry_date", f"Expiry date: {e2}.")
    if eff and exp and exp < eff:
        err("expiry_date", f"Expiry {exp:%d-%m-%Y} is before effective {eff:%d-%m-%Y}.")
    if eff and exp is None:
        warn("expiry_date", "No expiry date: the rule stays in force until changed.")

    nums = {}
    for k in ("min_value", "max_value", "min_weight", "max_weight"):
        n, e = _number(rule.get(k))
        nums[k] = n
        if e:
            err(k, f"'{rule.get(k)}' is {e}.")
        elif n is not None and n < 0:
            err(k, "Must be 0 or more.")
    for lo, hi in (("min_value", "max_value"), ("min_weight", "max_weight")):
        if nums[lo] is not None and nums[hi] is not None and nums[lo] > nums[hi]:
            err(hi, f"{lo} {nums[lo]} is above {hi} {nums[hi]}.")
    if (nums["min_value"] is not None or nums["max_value"] is not None):
        if not rule.get("currency"):
            err("currency", "A value threshold needs a currency.")
        if rule.get("value_basis") not in ("DV", "IV"):
            err("value_basis", "A value threshold needs the value basis DV or IV.")
    elif rule.get("value_basis") not in (None, "", "DV", "IV"):
        err("value_basis", "Value basis must be DV or IV.")

    for field_, list_name in (("region", "Validation.Region"), ("shipment_type", "Validation.B2B/B2C"),
                              ("currency", "Validation.Currency List"), ("country", "Validation.Country")):
        v = rule.get(field_)
        allowed = _list(cur, bid, list_name)
        if v and allowed and str(v).strip() not in allowed:
            warn(field_, f"'{v}' is not in {list_name} (reference list, not enforced; existing Import rows use "
                         "values outside it too — see Q-10).")
    if rule.get("other_logic"):
        warn("other_logic", "Other Logic is stored as text and not evaluated here; its syntax must be checked "
                            "by the rule engine's own parser.")
    codes = [c.strip() for c in str(rule.get("network_product_code") or "").split(",") if c.strip()]
    if codes:
        cur.execute("SELECT DISTINCT product_code FROM sirdb.import_rule_product_code WHERE batch_id = %s", (bid,))
        known = {r[0] for r in cur.fetchall()}
        new = [c for c in codes if c not in known]
        if new:
            warn("network_product_code", f"Code(s) not used by any Import rule yet: {', '.join(new)}.")
    if country and sirg_cd:
        cur.execute("""SELECT source_row_no FROM sirdb.import_rule WHERE batch_id = %s AND sirg_ref_country = %s
                       AND sirg_ref_sirg_cd = %s AND coalesce(shipment_type,'') = coalesce(%s,'')""",
                    (bid, country, sirg_cd, rule.get("shipment_type")))
        existing = [r[0] for r in cur.fetchall()]
        if existing:
            warn("sirg_cd", f"Import already has a {country} {sirg_cd} rule for {rule.get('shipment_type')} "
                            f"(rows {existing}) — check for overlap.")

    return {"valid": not errors, "errors": errors, "warnings": warnings, "batch_id": bid,
            "resolution": resolution.as_dict() if resolution else None, "sir_reference_lines": lines}


# --------------------------------------------------------------------------- #
# proposals → final Import
# --------------------------------------------------------------------------- #

PROPOSAL_FIELDS = ["region", "country", "shipment_type", "effective_date", "expiry_date", "network_product_code",
                   "value_basis", "currency", "min_value", "max_value", "min_weight", "max_weight", "other_logic",
                   "country_hold_code", "global_hold_code", "processing_type", "sirg_cd", "document_reference"]


def save_proposal(conn: psycopg.Connection, rule: dict[str, Any], actor: str) -> dict[str, Any]:
    with conn.cursor() as cur:
        result = validate_rule(cur, rule)
        vals = {k: rule.get(k) for k in PROPOSAL_FIELDS}
        vals["effective_date"] = _date(vals["effective_date"])[0]
        vals["expiry_date"] = _date(vals["expiry_date"])[0]
        vals["processing_type"] = vals["processing_type"] or PROC
        cur.execute(f"""INSERT INTO sirdb.rule_proposal ({", ".join(PROPOSAL_FIELDS)}, status, validation,
                        validated_batch_id, created_by) VALUES ({", ".join(["%s"] * len(PROPOSAL_FIELDS))},%s,%s,%s,%s)
                        RETURNING proposal_id""",
                    [vals[k] for k in PROPOSAL_FIELDS] + [
                        "VALIDATED" if result["valid"] else "DRAFT", json.dumps(result, default=str),
                        result["batch_id"], actor])
        pid = cur.fetchone()[0]
    conn.commit()
    return {"proposal_id": pid, **result}


def approve_proposal(conn: psycopg.Connection, proposal_id: int, actor: str) -> dict[str, Any]:
    """Re-validate against the current batch, then approve. Refused while any blocking error remains."""
    with conn.cursor() as cur:
        cur.execute(f"SELECT status, created_by, {', '.join(PROPOSAL_FIELDS)} FROM sirdb.rule_proposal "
                    "WHERE proposal_id = %s FOR UPDATE", (proposal_id,))
        row = cur.fetchone()
        if not row:
            raise ResolveError(f"No proposal {proposal_id}.")
        status, created_by, *values = row
        if status not in ("VALIDATED", "DRAFT"):
            raise ResolveError(f"Proposal {proposal_id} is {status}.")
        rule = dict(zip(PROPOSAL_FIELDS, values))
        result = validate_rule(cur, rule)
        if not result["valid"]:
            cur.execute("UPDATE sirdb.rule_proposal SET status = 'DRAFT', validation = %s WHERE proposal_id = %s",
                        (json.dumps(result, default=str), proposal_id))
            conn.commit()
            raise ResolveError(f"Proposal {proposal_id} has blocking errors: "
                               + "; ".join(e["message"] for e in result["errors"]))
        cur.execute("""UPDATE sirdb.rule_proposal SET status = 'APPROVED', approved_by = %s, approved_at = now(),
                       validation = %s, validated_batch_id = %s WHERE proposal_id = %s""",
                    (actor, json.dumps(result, default=str), result["batch_id"], proposal_id))
    conn.commit()
    return {"proposal_id": proposal_id, "status": "APPROVED", **result}


def final_import(cur) -> list[dict[str, Any]]:
    cur.execute("SELECT * FROM sirdb.v_import_final ORDER BY origin DESC, origin_row")
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def export_import(path: str | Path, url: Optional[str] = None) -> int:
    """Write the final Import dataset with the exact 17 Import headers (xlsx or csv)."""
    with connect(url, actor="export") as conn, conn.cursor() as cur:
        rows = final_import(cur)
    path = Path(path)
    if path.suffix.lower() == ".csv":
        import csv
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(IMPORT_HEADERS)
            w.writerows([[r[h] for h in IMPORT_HEADERS] for r in rows])
    else:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Import"
        ws.append(IMPORT_HEADERS)
        for r in rows:
            ws.append([_cell(r[h]) for h in IMPORT_HEADERS])
        wb.save(path)
    return len(rows)


def _cell(v: Any) -> Any:
    """Numbers back as numbers (the workbook stores thresholds as numbers); everything else as text."""
    if isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v):
        return int(v) if "." not in v else float(v)
    return v


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="SIR/SIRG resolution and Import export.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("resolve", help="resolve country + SIRG code")
    r.add_argument("country")
    r.add_argument("sirg_cd")
    r.add_argument("--processing-type", default=PROC)
    v = sub.add_parser("validate", help="validate a proposed rule (JSON file)")
    v.add_argument("rule_json")
    e = sub.add_parser("export", help="write the final Import dataset (.xlsx or .csv)")
    e.add_argument("path")
    args = ap.parse_args(argv)
    if args.cmd == "export":
        print(f"{export_import(args.path)} rows written to {args.path}")
        return
    with connect(actor="cli") as conn, conn.cursor() as cur:
        if args.cmd == "resolve":
            res = resolve_sirg(cur, args.country, args.sirg_cd, args.processing_type)
            out = {"resolution": res.as_dict(),
                   "sir_reference_lines": sir_reference_lines(cur, args.country, args.sirg_cd)}
        else:
            out = validate_rule(cur, json.loads(Path(args.rule_json).read_text(encoding="utf-8")))
    print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
    main()
