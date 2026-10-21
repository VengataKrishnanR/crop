"""Cell-value parsing shared by both reference sources.

The legacy workbook ingestion and the sirdb repository must turn the same cell
into the same typed value, or the parity test is meaningless; both use these.
sirdb keeps cells as text (``*_raw``), so dates may arrive as ``YYYY-MM-DD
HH:MM:SS`` -- the text form of a date-typed cell -- as well as ``DD-MM-YYYY``.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import PurePath
from typing import Any, Optional

# e.g. "M2c_6_5_ver_1_W29_2.10.9-beta.2_20262608-131409_...xlsx"
_VERSION_RE = re.compile(r"_((?:\d+\.){2}\d+-[A-Za-z]+\.\d+)_")

DATE_FORMATS = ("%d-%m-%Y", "%d-%m-%y", "%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S")


def workbook_version_from_name(name: str) -> str:
    """The version embedded in an M2C workbook file name, else the file stem."""
    path = PurePath(name)
    match = _VERSION_RE.search(path.name)
    return match.group(1) if match else path.stem[:64]


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def number(value: Any) -> Optional[float]:
    raw = text(value).replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def date(value: Any) -> Optional[dt.date]:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    raw = text(value)
    if not raw:
        return None
    for fmt in DATE_FORMATS:
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def is_placeholder(value: str) -> bool:
    """Empty values and TEST|TEST|... placeholders never join anything. (A TBD hold code inside an
    otherwise real key, e.g. IL|Import|TBD|CIDM, still joins: both sides carry the same key.)"""
    return not value or any(p.strip().upper() == "TEST" for p in value.split("|"))


def split_attribute_ids(raw: Any) -> list[str]:
    """``AttributeID`` holds one or more ids joined by ``&`` (sometimes ``&&``)."""
    joined = text(raw)
    if not joined:
        return []
    return [part.strip() for part in joined.replace("&&", "&").split("&") if part.strip()]


def sirg_code(sirg_reference: str) -> str:
    """``BG|Import|IOSS`` style references carry the SIRG code in slot 3."""
    parts = sirg_reference.split("|")
    if len(parts) == 3 and set(parts) != {"TEST"}:
        return parts[2]
    return ""
