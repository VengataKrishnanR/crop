"""Phase 3 — load an M2C workbook into the SIR/SIRG PostgreSQL database.

Idempotent:
  * the same file (same SHA-256) is loaded once; loading it again changes nothing;
  * a half-finished or failed load of that file is removed and redone;
  * a different file is a new batch — earlier batches stay, untouched, as history.

Re-import policy: the newest successfully loaded batch becomes *current* (the one the
views and resolvers use) unless ``--keep-current`` is given. Earlier batches are never
updated or deleted by the loader.

Everything happens in one transaction: either the whole workbook is in, or nothing is.

Run:  python -m tools.sirdb.loader <workbook.xlsx> [--keep-current] [--report docs/sirdb/generated]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

from .db import connect, database_url, redacted
from .profile import (
    DOCREF_FORMULA, IMPORT_COLS, SREF_COLS, SREF_FORMULA, is_placeholder, parse_dmy, profile, split_ref,
)
from .workbook import Workbook, read_workbook

# Which normalised table each sheet's data rows go to.
SHEET_TARGET = {
    "Import": "import_rule", "SIR Reference": "sir_reference", "Technical SIR": "technical_sir",
    "Technical SIRG": "technical_sirg", "Other Logic": "logic_expression", "Validation": "reference_list_item",
    "Sheet2": "reference_list_item", "Sheet1": "inferred_record", "Export": None,
}
TSIRG_SCHEMA = ["sirg_technical_id", "sirg_cd", "sirg_nm", "sirg_dsc", "dhl_ctry_cd", "processing_type",
                "cmpt_nm", "sir_technical_id"]


def _snake(header: Optional[str], col: int) -> str:
    if header is None or not str(header).strip():
        return f"col_{col:02d}_unheaded"
    s = re.sub(r"[^0-9a-zA-Z]+", "_", str(header)).strip("_").lower()
    return s or f"col_{col:02d}_unheaded"


def _text(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v)) if abs(v) < 1e15 else repr(v)
    return str(v)


def _num(v: Any) -> Optional[Decimal]:
    if v in (None, "") or isinstance(v, bool):
        return None
    try:
        return Decimal(str(v).strip().replace(",", "."))
    except InvalidOperation:
        return None


def _flag(v: Any) -> Optional[bool]:
    s = str(v).strip().upper() if v not in (None, "") else ""
    return {"Y": True, "N": False}.get(s)


# --------------------------------------------------------------------------- #

def load(path: str | Path, url: Optional[str] = None, actor: str = "loader",
         make_current: bool = True) -> dict[str, Any]:
    wb = read_workbook(path)
    with connect(url, actor=actor) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT batch_id, status FROM sirdb.import_batch WHERE file_sha256 = %s", (wb.sha256,))
            existing = cur.fetchone()
            if existing and existing[1] == "LOADED":
                cur.execute("SELECT batch_id, is_current, summary FROM sirdb.import_batch WHERE batch_id = %s",
                            (existing[0],))
                bid, current, summary = cur.fetchone()
                if make_current and not current:
                    _set_current(cur, bid)
                    conn.commit()
                return {"batch_id": bid, "status": "ALREADY_LOADED", "sha256": wb.sha256, "summary": summary}
            if existing:   # LOADING / FAILED: discard the partial load and redo it
                cur.execute("DELETE FROM sirdb.import_batch WHERE batch_id = %s", (existing[0],))
            cur.execute("""INSERT INTO sirdb.import_batch (source_filename, file_sha256, file_size, loaded_by)
                           VALUES (%s, %s, %s, %s) RETURNING batch_id""",
                        (wb.path.name, wb.sha256, wb.size, actor))
            bid = cur.fetchone()[0]
            try:
                summary = _load_batch(cur, bid, wb)
                cur.execute("UPDATE sirdb.import_batch SET status = 'LOADED', summary = %s WHERE batch_id = %s",
                            (json.dumps(summary), bid))
                if make_current:
                    _set_current(cur, bid)
            except Exception:
                conn.rollback()
                raise
        conn.commit()
    return {"batch_id": bid, "status": "LOADED", "sha256": wb.sha256, "summary": summary}


def _set_current(cur, bid: int) -> None:
    cur.execute("UPDATE sirdb.import_batch SET is_current = false WHERE is_current AND batch_id <> %s", (bid,))
    cur.execute("UPDATE sirdb.import_batch SET is_current = true WHERE batch_id = %s", (bid,))


def _load_batch(cur, bid: int, wb: Workbook) -> dict[str, Any]:
    # ---- raw: sheets, columns, rows, cells ------------------------------------
    for s in wb.sheets.values():
        cur.execute("""INSERT INTO sirdb.source_sheet (batch_id, sheet_name, sheet_index, used_range, max_row, max_col,
                       headerless, autofilter, data_validations) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (bid, s.name, s.index, s.dimensions, s.max_row, s.max_col, s.headerless, s.autofilter,
                     json.dumps(s.data_validations)))
        from openpyxl.utils import get_column_letter
        cur.executemany("""INSERT INTO sirdb.source_column (batch_id, sheet_name, col_index, col_letter, header_text,
                           provisional_name) VALUES (%s,%s,%s,%s,%s,%s)""",
                        [(bid, s.name, c, get_column_letter(c), s.headers[c - 1], _snake(s.headers[c - 1], c))
                         for c in range(1, s.max_col + 1)])
        target = SHEET_TARGET.get(s.name)
        rows, cells = [], []
        for r in sorted(s.rows):
            record = [_jsonable(v) for v in s.record(r)]
            header = (not s.headerless) and r == 1
            status = "HEADER" if header else ("INFERRED" if target == "inferred_record"
                                              else "MAPPED" if target else "UNMAPPED")
            rows.append((bid, s.name, r, header, json.dumps(record),
                         hashlib.sha256(json.dumps(record).encode()).hexdigest(),
                         None if header else target, status))
            for c in s.rows[r]:
                cells.append((bid, s.name, r, c.col, c.letter, _text(c.value), _vtype(c.value), c.formula))
        cur.executemany("""INSERT INTO sirdb.source_row (batch_id, sheet_name, row_no, is_header, record, row_sha256,
                           mapped_to, map_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", rows)
        cur.executemany("""INSERT INTO sirdb.source_cell (batch_id, sheet_name, row_no, col_index, col_letter,
                           value_text, value_type, formula) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", cells)

    counts: dict[str, int] = {}

    # ---- Technical SIR / SIRG -------------------------------------------------
    t = wb["Technical SIR"]
    data = [(bid, r, t.value(r, 4), t.value(r, 1), t.value(r, 2), t.value(r, 3)) for r in t.data_rows()]
    cur.executemany("""INSERT INTO sirdb.technical_sir (batch_id, source_row_no, sir_technical_id, cmpt_nm, nm, dsc)
                       VALUES (%s,%s,%s,%s,%s,%s)""", data)
    counts["technical_sir"] = len(data)
    g = wb["Technical SIRG"]
    data = [(bid, r, *[_text(g.value(r, c)) for c in range(1, 9)]) for r in g.data_rows()]
    cur.executemany("""INSERT INTO sirdb.technical_sirg (batch_id, source_row_no, sirg_technical_id, sirg_cd, sirg_nm,
                       sirg_dsc, dhl_ctry_cd, processing_type, cmpt_nm, sir_technical_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", data)
    counts["technical_sirg"] = len(data)

    # ---- Other Logic, lists, template, Sheet1 -----------------------------------
    o = wb["Other Logic"]
    data = [(bid, r, str(o.value(r, 1))) for r in o.data_rows()]
    cur.executemany("INSERT INTO sirdb.logic_expression (batch_id, source_row_no, expression) VALUES (%s,%s,%s)", data)
    counts["logic_expression"] = len(data)

    items = 0
    lists = [("Validation." + (wb["Validation"].headers[c - 1] or f"col_{c:02d}"), "Validation", c,
              wb["Validation"].headers[c - 1]) for c in range(1, wb["Validation"].max_col + 1)]
    lists.append(("Sheet2", "Sheet2", 1, None))
    for name, sheet, col, header in lists:
        cur.execute("""INSERT INTO sirdb.reference_list (batch_id, list_name, origin_sheet, origin_col, origin_header)
                       VALUES (%s,%s,%s,%s,%s) RETURNING list_id""", (bid, name, sheet, col, header))
        lid = cur.fetchone()[0]
        sh = wb[sheet]
        vals = [(r, sh.value(r, col)) for r in sh.data_rows() if sh.value(r, col) not in (None, "")]
        cur.executemany("""INSERT INTO sirdb.reference_list_item (list_id, position, source_row_no, value_raw,
                           value_normalized, normalization) VALUES (%s,%s,%s,%s,%s,%s)""",
                        [(lid, i + 1, r, _text(v), _text(v).strip(),
                          "trimmed leading/trailing spaces" if _text(v) != _text(v).strip() else None)
                         for i, (r, v) in enumerate(vals)])
        items += len(vals)
    counts["reference_list_item"] = items

    e = wb["Export"]
    cur.executemany("""INSERT INTO sirdb.template_column (batch_id, template_name, position, header_text, in_import)
                       VALUES (%s,'Export',%s,%s,%s)""",
                    [(bid, i + 1, h, h in wb["Import"].headers) for i, h in enumerate(e.headers) if h])
    s1 = wb["Sheet1"]
    for r in s1.data_rows():
        rec = s1.record(r)
        cur.execute("""INSERT INTO sirdb.inferred_record (batch_id, source_sheet, source_row_no, inferred_as, fields,
                       evidence) VALUES (%s,'Sheet1',%s,'technical_sirg',%s,%s)""",
                    (bid, r, json.dumps(dict(zip(TSIRG_SCHEMA, [_jsonable(v) for v in rec]))),
                     "8 values in Technical SIRG column order: GUID, SIRG code, name, blank description, country, "
                     "IMP_CLR, component, GUID. Inferred, not declared (Q-07)."))

    # ---- Import rules -----------------------------------------------------------
    imp = wb["Import"]
    rule_rows, codes = [], []
    for r in imp.data_rows():
        v = lambda k: imp.value(r, IMPORT_COLS[k])  # noqa: E731
        eff, eff_err = parse_dmy(v("effective_date"))
        exp, exp_err = parse_dmy(v("expiry_date"))
        p_formula = imp.formula(r, IMPORT_COLS["document_reference"])
        p, q = v("document_reference"), v("sirg_document_reference")
        q_parts = split_ref(q)
        q_ph, p_ph = is_placeholder(q), is_placeholder(p)
        q_ok = not q_ph and len(q_parts) == 3
        generation = ("HOLD_CODE" if p_formula and DOCREF_FORMULA.match(p_formula)
                      else "SIRG" if q_ok else "UNCLASSIFIED")
        rule_rows.append((
            bid, r, _text(v("region")), _text(v("country")), _text(v("shipment_type")),
            _text(v("effective_date")), eff, eff_err, _text(v("expiry_date")), exp, exp_err,
            _text(v("network_product_code")), _text(v("value_basis")), _text(v("currency")),
            _text(v("min_value")), _num(v("min_value")), _text(v("max_value")), _num(v("max_value")),
            _text(v("min_weight")), _num(v("min_weight")), _text(v("max_weight")), _num(v("max_weight")),
            _text(v("other_logic")), _text(v("country_hold_code")), _text(v("global_hold_code")),
            _text(p), p_formula, "FORMULA" if p_formula else ("LITERAL" if p not in (None, "") else "EMPTY"),
            _text(q), q_parts[0] if q_ok else None, q_parts[1] if q_ok else None, q_parts[2] if q_ok else None,
            p_ph, q_ph, generation))
        for i, code in enumerate([c.strip() for c in str(v("network_product_code") or "").split(",") if c.strip()]):
            codes.append((bid, r, i + 1, code))
    cur.executemany(f"""INSERT INTO sirdb.import_rule (batch_id, source_row_no, region, country, shipment_type,
        effective_date_raw, effective_date, effective_date_issue, expiry_date_raw, expiry_date, expiry_date_issue,
        network_product_code_raw, value_basis, currency, min_value_raw, min_value, max_value_raw, max_value,
        min_weight_raw, min_weight, max_weight_raw, max_weight, other_logic, country_hold_code, global_hold_code,
        document_reference, document_reference_formula, document_reference_kind, sirg_document_reference,
        sirg_ref_country, sirg_ref_direction, sirg_ref_sirg_cd, is_document_ref_placeholder, is_sirg_ref_placeholder,
        rule_generation) VALUES ({",".join(["%s"] * 35)})""", rule_rows)
    cur.executemany("""INSERT INTO sirdb.import_rule_product_code (batch_id, source_row_no, position, product_code)
                       VALUES (%s,%s,%s,%s)""", codes)
    counts["import_rule"] = len(rule_rows)

    # ---- SIR Reference ----------------------------------------------------------
    sref = wb["SIR Reference"]
    ref_rows, attrs = [], []
    for r in sref.data_rows():
        v = lambda k: sref.value(r, SREF_COLS[k])  # noqa: E731
        a_formula = sref.formula(r, 1)
        m = SREF_FORMULA.match(a_formula or "")
        b = v("sir_document_reference")
        bp = split_ref(b)
        b_ok = not is_placeholder(b) and len(bp) == 4
        ref_rows.append((
            bid, r, _text(v("document_reference")), a_formula, int(m.group(1)) if m else None,
            _text(b), *(bp if b_ok else [None] * 4),
            _text(v("waived_if_whitelisted")), _flag(v("waived_if_whitelisted")),
            _text(v("waived_to_validate")), _flag(v("waived_to_validate")),
            _text(v("check_if_service_code")), _text(v("cmpt_nm")), _text(v("sir_technical_id")),
            _text(v("attribute_id")), _text(v("col_09_unheaded")),
            is_placeholder(v("document_reference")), is_placeholder(b)))
        ids = [x for x in re.split(r"&+", str(v("attribute_id") or "")) if x.strip()]
        labels = [x.strip() for x in re.split(r"&+", str(v("col_09_unheaded") or "")) if x.strip()]
        aligned = len(ids) == len(labels)
        for i, a in enumerate(ids):
            attrs.append((bid, r, i + 1, a.strip(), labels[i] if aligned else None))
    cur.executemany(f"""INSERT INTO sirdb.sir_reference (batch_id, source_row_no, document_reference,
        document_reference_formula, formula_target_import_row, sir_document_reference, sdr_country, sdr_direction,
        sdr_sirg_cd, sdr_cmpt_nm, waived_if_whitelisted_raw, waived_if_whitelisted, waived_to_validate_raw,
        waived_to_validate, check_if_service_code, cmpt_nm, sir_technical_id, attribute_id_raw, col_09_unheaded,
        is_document_ref_placeholder, is_sdr_placeholder) VALUES ({",".join(["%s"] * 21)})""", ref_rows)
    cur.executemany("""INSERT INTO sirdb.sir_reference_attribute (batch_id, source_row_no, position, attribute_id,
                       col_09_entry) VALUES (%s,%s,%s,%s,%s)""", attrs)
    counts["sir_reference"] = len(ref_rows)
    counts["sir_reference_attribute"] = len(attrs)

    # ---- findings -----------------------------------------------------------------
    rep = profile(wb)
    cur.executemany("""INSERT INTO sirdb.load_issue (batch_id, code, severity, sheet_name, row_no, column_name,
                       value_text, message, basis) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    [(bid, f["code"], f["severity"], f["sheet"], f["row"], f["column"],
                      None if f["value"] is None else str(f["value"]), f["message"], f["basis"])
                     for f in rep["findings"]])
    return {"normalised": counts, "findings": rep["summary"]["findings"],
            "sheets": {s.name: len(s.data_rows()) for s in wb.sheets.values()}}


def _jsonable(v: Any) -> Any:
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


def _vtype(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if isinstance(v, dt.datetime):
        return "datetime"
    if isinstance(v, dt.date):
        return "date"
    return "str"


# --------------------------------------------------------------------------- #
# reconciliation: every worksheet, every source row
# --------------------------------------------------------------------------- #

RECON_SQL = """
SELECT s.sheet_name,
       count(*) FILTER (WHERE NOT r.is_header)                         AS source_rows,
       count(*) FILTER (WHERE r.map_status = 'MAPPED')                 AS mapped,
       count(*) FILTER (WHERE r.map_status = 'INFERRED')               AS inferred,
       count(*) FILTER (WHERE r.map_status = 'UNMAPPED' AND NOT r.is_header) AS unmapped,
       (SELECT count(*) FROM sirdb.source_cell c WHERE c.batch_id = s.batch_id AND c.sheet_name = s.sheet_name) AS cells,
       (SELECT count(*) FROM sirdb.source_cell c WHERE c.batch_id = s.batch_id AND c.sheet_name = s.sheet_name
                                                AND c.formula IS NOT NULL)  AS formulas,
       (SELECT count(*) FROM sirdb.load_issue i WHERE i.batch_id = s.batch_id AND i.sheet_name = s.sheet_name
                                               AND i.severity = 'warning') AS warnings,
       (SELECT count(*) FROM sirdb.load_issue i WHERE i.batch_id = s.batch_id AND i.sheet_name = s.sheet_name
                                               AND i.severity = 'error')   AS errors
FROM sirdb.source_sheet s
LEFT JOIN sirdb.source_row r ON r.batch_id = s.batch_id AND r.sheet_name = s.sheet_name
WHERE s.batch_id = %s
GROUP BY s.batch_id, s.sheet_name, s.sheet_index ORDER BY s.sheet_index
"""

NORMALISED_SQL = {
    "Import": "SELECT count(*) FROM sirdb.import_rule WHERE batch_id = %s",
    "SIR Reference": "SELECT count(*) FROM sirdb.sir_reference WHERE batch_id = %s",
    "Technical SIR": "SELECT count(*) FROM sirdb.technical_sir WHERE batch_id = %s",
    "Technical SIRG": "SELECT count(*) FROM sirdb.technical_sirg WHERE batch_id = %s",
    "Other Logic": "SELECT count(*) FROM sirdb.logic_expression WHERE batch_id = %s",
    "Sheet1": "SELECT count(*) FROM sirdb.inferred_record WHERE batch_id = %s",
    "Export": "SELECT count(*) FROM sirdb.template_column WHERE batch_id = %s",
}


def reconcile(batch_id: int, url: Optional[str] = None) -> list[dict[str, Any]]:
    out = []
    with connect(url, actor="reconcile") as conn, conn.cursor() as cur:
        cur.execute(RECON_SQL, (batch_id,))
        cols = [d.name for d in cur.description]
        for row in cur.fetchall():
            rec = dict(zip(cols, row))
            sql = NORMALISED_SQL.get(rec["sheet_name"])
            if sql:
                cur.execute(sql, (batch_id,))
                rec["normalised_rows"] = cur.fetchone()[0]
            elif rec["sheet_name"] in ("Validation", "Sheet2"):
                cur.execute("""SELECT count(*) FROM sirdb.reference_list_item i JOIN sirdb.reference_list l USING (list_id)
                               WHERE l.batch_id = %s AND l.origin_sheet = %s""", (batch_id, rec["sheet_name"]))
                rec["normalised_rows"] = cur.fetchone()[0]
            out.append(rec)
    return out


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="Load an M2C workbook into the SIR/SIRG database.")
    ap.add_argument("workbook")
    ap.add_argument("--url")
    ap.add_argument("--actor", default="loader")
    ap.add_argument("--keep-current", action="store_true", help="do not make this batch current")
    ap.add_argument("--report", help="write load_reconciliation.md into this folder")
    args = ap.parse_args(argv)
    print(f"database: {redacted(database_url(args.url))}")
    res = load(args.workbook, args.url, actor=args.actor, make_current=not args.keep_current)
    print(json.dumps(res, indent=2, default=str))
    rec = reconcile(res["batch_id"], args.url)
    lines = ["| Sheet | Source rows | Mapped | Inferred | Unmapped | Normalised rows | Cells | Formulas | Warnings | Errors |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    lines += [f"| {r['sheet_name']} | {r['source_rows']} | {r['mapped']} | {r['inferred']} | {r['unmapped']} | "
              f"{r.get('normalised_rows', '—')} | {r['cells']} | {r['formulas']} | {r['warnings']} | {r['errors']} |"
              for r in rec]
    print("\n".join(lines))
    if args.report:
        out = Path(args.report)
        out.mkdir(parents=True, exist_ok=True)
        (out / "load_reconciliation.md").write_text(
            f"# Load reconciliation — batch {res['batch_id']}\n\n- File SHA-256: `{res['sha256']}`\n"
            f"- Status: {res['status']}\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
