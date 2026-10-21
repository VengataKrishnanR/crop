"""Field-by-field comparison of two reference repositories (legacy vs sirdb).

Used by the parity test and by ``scripts/reference_parity.py``. Accepted, documented
differences (docs/adr/0003) are reported separately and do not count as drift:

* ``EXPORT_ROWS`` -- the legacy ingestion also loads Export-sheet rows; sirdb loads
  the Import sheet only (design decision 7: Import first).
* ``PROPOSAL_ROWS`` -- sirdb's ``v_import_final`` adds APPROVED platform proposals,
  which have no workbook row.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, fields
from typing import Any, Optional

from .base import ReferenceRepository, ReferenceRule

_RULE_FIELDS = [f.name for f in fields(ReferenceRule) if f.name not in ("id", "bindings")]


@dataclass(frozen=True)
class Difference:
    section: str
    key: str
    field: str
    legacy: Any
    sirdb: Any

    def line(self) -> str:
        return f"{self.section} {self.key} {self.field}: legacy={self.legacy!r} sirdb={self.sirdb!r}"


@dataclass
class ParityReport:
    differences: list[Difference]
    accepted: dict[str, int]
    counts: dict[str, tuple[int, int]]

    @property
    def clean(self) -> bool:
        return not self.differences


def _binding_key(b: Any) -> tuple:
    return (b.sir_id or "", b.cmpt_nm or "", bool(b.waived_if_whitelisted), bool(b.waived_to_validate),
            b.check_service_code or "", tuple(b.attribute_ids or ()), b.sirg_cd or "")


def compare(legacy: ReferenceRepository, sirdb: ReferenceRepository, country: Optional[str] = None) -> ParityReport:
    diffs: list[Difference] = []
    accepted: Counter[str] = Counter()

    legacy_rows = legacy.baseline_rules(country)
    sirdb_rows = sirdb.baseline_rules(country)
    accepted["EXPORT_ROWS"] = sum(1 for r in legacy_rows if r.direction != "Import")
    accepted["PROPOSAL_ROWS"] = sum(1 for r in sirdb_rows if r.row_no is None)
    left = {r.row_no: r for r in legacy_rows if r.direction == "Import"}
    right = {r.row_no: r for r in sirdb_rows if r.row_no is not None}
    for row_no in sorted(set(left) | set(right), key=lambda n: n or 0):
        a, b = left.get(row_no), right.get(row_no)
        key = f"Import row {row_no}"
        if a is None or b is None:
            diffs.append(Difference("rules", key, "(row)", "present" if a else "missing", "present" if b else "missing"))
            continue
        for name in _RULE_FIELDS:
            va, vb = getattr(a, name), getattr(b, name)
            if va != vb:
                diffs.append(Difference("rules", f"{key} ({a.ctry_cd})", name, va, vb))
        ba, bb = Counter(map(_binding_key, a.bindings)), Counter(map(_binding_key, b.bindings))
        if ba != bb:
            diffs.append(Difference("bindings", f"{key} ({a.ctry_cd})", "bindings",
                                    sorted((ba - bb).elements()), sorted((bb - ba).elements())))

    pa, pb = legacy.permitted_values(), sirdb.permitted_values()
    for name in sorted(set(pa) | set(pb)):
        only_a, only_b = pa.get(name, set()) - pb.get(name, set()), pb.get(name, set()) - pa.get(name, set())
        if only_a or only_b:
            diffs.append(Difference("permitted", name, "values", sorted(only_a), sorted(only_b)))

    for section, la, lb in (
        ("mirror_sir", legacy.mirror_sir(), sirdb.mirror_sir()),
        ("mirror_sirg", legacy.mirror_sirg(country), sirdb.mirror_sirg(country)),
    ):
        ca, cb = Counter(la), Counter(lb)
        for item in sorted((ca - cb).elements(), key=repr):
            diffs.append(Difference(section, getattr(item, "sir_id", "") or getattr(item, "sirg_id", ""),
                                    "(row)", item, None))
        for item in sorted((cb - ca).elements(), key=repr):
            diffs.append(Difference(section, getattr(item, "sir_id", "") or getattr(item, "sirg_id", ""),
                                    "(row)", None, item))

    ta, tb = legacy.expression_templates(), sirdb.expression_templates()
    if ta != tb:
        diffs.append(Difference("templates", "Other Logic", "palette", [t for t in ta if t not in tb],
                                [t for t in tb if t not in ta] or "same entries, different order"))

    counts = {"import_rows": (len(left), len(right)), "mirror_sir": (len(legacy.mirror_sir()), len(sirdb.mirror_sir())),
              "templates": (len(ta), len(tb))}
    return ParityReport(differences=diffs, accepted=dict(accepted), counts=counts)
