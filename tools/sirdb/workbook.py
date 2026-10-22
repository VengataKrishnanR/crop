"""Lossless reader for the M2C workbook.

Every non-empty cell is returned with its sheet, row, column, header, the cached
value Excel saved and — separately — the formula text, if the cell holds a
formula. Nothing is trimmed, converted or repaired here; normalisation happens
later and is stored next to the source value, never instead of it.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import openpyxl
from openpyxl.utils import get_column_letter

# Sheets whose first row is data, not a header (verified in Phase 1).
HEADERLESS_SHEETS = {"Sheet1", "Sheet2"}


@dataclass
class Cell:
    row: int
    col: int
    letter: str
    header: Optional[str]
    value: Any                 # cached value as saved by Excel
    formula: Optional[str]     # formula text, e.g. =CONCATENATE(B2,"|Import|",N2,"|",O2)
    data_type: str             # openpyxl type of the formula cell: s, n, d, b, f


@dataclass
class Sheet:
    name: str
    index: int
    dimensions: str
    max_row: int
    max_col: int
    headerless: bool
    headers: list[Optional[str]]              # column order preserved; None = no header
    autofilter: Optional[str]
    data_validations: list[dict[str, Any]]
    rows: dict[int, list[Cell]] = field(default_factory=dict)   # row number -> cells (non-empty only)

    @property
    def first_data_row(self) -> int:
        return 1 if self.headerless else 2

    def data_rows(self) -> list[int]:
        return [r for r in sorted(self.rows) if r >= self.first_data_row]

    def value(self, row: int, col: int) -> Any:
        for c in self.rows.get(row, []):
            if c.col == col:
                return c.value
        return None

    def formula(self, row: int, col: int) -> Optional[str]:
        for c in self.rows.get(row, []):
            if c.col == col:
                return c.formula
        return None

    def record(self, row: int) -> list[Any]:
        return [self.value(row, c) for c in range(1, self.max_col + 1)]


@dataclass
class Workbook:
    path: Path
    sha256: str
    size: int
    sheets: dict[str, Sheet]

    def __getitem__(self, name: str) -> Sheet:
        return self.sheets[name]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _plain(v: Any) -> Any:
    if isinstance(v, dt.datetime):
        return v.isoformat()
    if isinstance(v, dt.date):
        return v.isoformat()
    return v


def read_workbook(path: str | Path) -> Workbook:
    """Read every sheet twice (formulas, cached values) and merge per cell."""
    path = Path(path)
    wf = openpyxl.load_workbook(path, data_only=False)
    wv = openpyxl.load_workbook(path, data_only=True)
    sheets: dict[str, Sheet] = {}
    for index, ws in enumerate(wf.worksheets):
        vs = wv[ws.title]
        headerless = ws.title in HEADERLESS_SHEETS
        headers = [None] * ws.max_column if headerless else [
            (str(ws.cell(1, c).value) if ws.cell(1, c).value is not None else None)
            for c in range(1, ws.max_column + 1)]
        sheet = Sheet(
            name=ws.title, index=index, dimensions=ws.dimensions, max_row=ws.max_row, max_col=ws.max_column,
            headerless=headerless, headers=headers, autofilter=ws.auto_filter.ref,
            data_validations=[{"type": d.type, "sqref": str(d.sqref), "formula1": d.formula1}
                              for d in ws.data_validations.dataValidation],
        )
        for row in ws.iter_rows():
            for c in row:
                raw = c.value
                if raw is None or raw == "":
                    continue
                is_formula = isinstance(raw, str) and raw.startswith("=")
                cached = vs.cell(c.row, c.column).value
                sheet.rows.setdefault(c.row, []).append(Cell(
                    row=c.row, col=c.column, letter=get_column_letter(c.column),
                    header=headers[c.column - 1] if c.column - 1 < len(headers) else None,
                    value=_plain(cached if is_formula else raw),
                    formula=raw if is_formula else None, data_type=c.data_type))
        sheets[ws.title] = sheet
    return Workbook(path=path, sha256=file_sha256(path), size=path.stat().st_size, sheets=sheets)
