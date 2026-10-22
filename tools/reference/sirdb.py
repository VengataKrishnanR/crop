"""Reference data from sirdb -- the single source of truth (docs/adr/0003).

Rows come from ``sirdb.v_import_final`` (the downstream contract: 17 Import
columns, workbook rows of the current batch plus APPROVED proposals); bindings
from ``sirdb.v_import_rule_sir_reference`` (sirdb's documented SIR Reference
joins); the catalogue mirror, Validation lists and Other Logic palette from the
current batch's tables. Values are typed with :mod:`tools.reference.values`, the
same parsers the legacy ingestion uses. Read-only: no statement here writes.
``version`` arguments are accepted for interface parity and ignored: sirdb always
serves its current batch.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Engine, text

from . import values as v
from .base import MirrorSirgRow, MirrorSirRow, ReferenceBinding, ReferenceRule

# Validation tab header -> canonical field, as in the legacy ingestion.
PERMITTED_LISTS: dict[str, str] = {
    "Validation.Region": "region",
    "Validation.B2B/B2C": "shipment_type",
    "Validation.Declared Value/ Intristic Value": "value_basis",
    "Validation.Currency List": "currency",
    "Validation.Waived if Whitelisted": "waiver",
    "Validation.Country": "country",
}

_CURRENT = "(SELECT batch_id FROM sirdb.v_current_batch)"


class SirdbReferenceRepository:
    source = "sirdb"

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _rows(self, sql: str, **params: Any) -> list[Any]:
        with self._engine.connect() as conn:
            return list(conn.execute(text(sql), params))

    def workbook_version(self) -> Optional[str]:
        rows = self._rows("SELECT batch_id, source_filename FROM sirdb.import_batch WHERE is_current")
        return v.workbook_version_from_name(rows[0].source_filename) if rows else None

    def batch(self) -> Optional[dict[str, Any]]:
        rows = self._rows("SELECT batch_id, source_filename, file_sha256 FROM sirdb.import_batch WHERE is_current")
        return dict(rows[0]._mapping) if rows else None

    def baseline_rules(self, country: Optional[str] = None) -> list[ReferenceRule]:
        where = 'WHERE f."Country" = :country' if country else ""
        rows = self._rows(f'SELECT * FROM sirdb.v_import_final f {where} '
                          'ORDER BY f.origin DESC, f.origin_row', country=(country or "").upper())
        bindings = self._bindings()
        out: list[ReferenceRule] = []
        for r in rows:
            m = r._mapping
            workbook = m["origin"] == "WORKBOOK"
            sirg_cd = v.sirg_code(v.text(m["SIRG Document Reference"]))
            row_no = int(m["origin_row"]) if workbook else None
            key = f"sirdb:{m['origin_batch_id']}:{m['origin_row']}" if workbook else f"sirdb:proposal:{m['origin_row']}"
            out.append(ReferenceRule(
                id=key, row_no=row_no, direction="Import",
                region=v.text(m["Region"]) or None, ctry_cd=v.text(m["Country"]),
                shipment_type=v.text(m["B2B/B2C"]) or None,
                effective_date=v.date(m["Effective Date (DD-MM-YYY)"]),
                expiry_date=v.date(m["Date of Expiry (DD-MM-YYY)"]),
                network_product_codes=v.text(m["Network Product Code"]) or None,
                value_basis=v.text(m["Declared Value/ Intristic Value"]) or None,
                currency=v.text(m["Currency"]) or None,
                min_value=v.number(m["Min Value (>=)"]), max_value=v.number(m["Max Value (<=)"]),
                min_weight=v.number(m["Shipt Weight (kg) (>=)"]), max_weight=v.number(m["Shipt Weight (kg) (<=)"]),
                other_logic=v.text(m["Other Logic"]) or None,
                country_hold_cd=v.text(m["Country Hold Code"]) or None,
                global_hold_cd=v.text(m["Global Hold Code"]) or None,
                sirg_cd=sirg_cd or None, doc_reference=v.text(m["Document Reference"]) or None,
                bindings=tuple(ReferenceBinding(
                    sirg_cd=sirg_cd or None, sir_id=b["sir_technical_id"], cmpt_nm=b["cmpt_nm"],
                    waived_if_whitelisted=bool(b["waived_if_whitelisted"]),
                    waived_to_validate=bool(b["waived_to_validate"]),
                    check_service_code=v.text(b["check_if_service_code"]) or None,
                    attribute_ids=tuple(v.split_attribute_ids(b["attribute_id_raw"])),
                ) for b in bindings.get(row_no, [])) if workbook else (),
            ))
        return out

    def _bindings(self) -> dict[int, list[dict[str, Any]]]:
        rows = self._rows("SELECT import_row, sir_reference_row, cmpt_nm, sir_technical_id, waived_if_whitelisted, "
                          "waived_to_validate, check_if_service_code, attribute_id_raw "
                          f"FROM sirdb.v_import_rule_sir_reference WHERE batch_id = {_CURRENT} "
                          "ORDER BY import_row, sir_reference_row")
        out: dict[int, list[dict[str, Any]]] = {}
        for r in rows:
            out.setdefault(r.import_row, []).append(dict(r._mapping))
        return out

    def permitted_values(self, version: Optional[str] = None) -> dict[str, set[str]]:
        rows = self._rows("SELECT l.list_name, i.value_normalized FROM sirdb.reference_list l "
                          "JOIN sirdb.reference_list_item i USING (list_id) "
                          f"WHERE l.batch_id = {_CURRENT}")
        out: dict[str, set[str]] = {}
        for name, value in rows:
            canonical = PERMITTED_LISTS.get(name)
            if canonical and value:
                out.setdefault(canonical, set()).add(value)
        return out

    def mirror_sir(self, version: Optional[str] = None) -> list[MirrorSirRow]:
        rows = self._rows("SELECT sir_technical_id, cmpt_nm, nm, dsc FROM sirdb.technical_sir "
                          f"WHERE batch_id = {_CURRENT} ORDER BY source_row_no")
        return [MirrorSirRow(sir_id=v.text(r[0]), cmpt_nm=v.text(r[1]) or None, nm=v.text(r[2]) or None,
                             dsc=v.text(r[3]) or None) for r in rows if v.text(r[0])]

    def mirror_sirg(self, country: Optional[str] = None, version: Optional[str] = None) -> list[MirrorSirgRow]:
        rows = self._rows("SELECT sirg_technical_id, sirg_cd, sirg_nm, sirg_dsc, dhl_ctry_cd, processing_type, "
                          "cmpt_nm, sir_technical_id FROM sirdb.technical_sirg "
                          f"WHERE batch_id = {_CURRENT} AND (:country = '' OR dhl_ctry_cd = :country) "
                          "ORDER BY source_row_no", country=(country or "").upper())
        return [MirrorSirgRow(*[v.text(x) or None for x in r]) for r in rows if v.text(r[0])]  # type: ignore[arg-type]

    def expression_templates(self, version: Optional[str] = None) -> list[str]:
        rows = self._rows(f"SELECT expression FROM sirdb.logic_expression WHERE batch_id = {_CURRENT} "
                          "ORDER BY source_row_no")
        return [v.text(r[0]) for r in rows if v.text(r[0])]
