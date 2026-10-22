"""The reference-data interface and its value types (docs/adr/0003).

Reference data = what the M2C workbook provides: the baseline Import rows and
their SIR Reference bindings, the Technical SIR / SIRG catalogue mirror, the
Validation lists and the Other Logic palette. Two implementations exist for one
release: :class:`~tools.reference.sirdb.SirdbReferenceRepository` (the single
source of truth) and :class:`~tools.reference.legacy.LegacyReferenceRepository`
(the app's own workbook ingestion). Both return these frozen value types, so a
parity test can compare them field by field.

The value types use the same attribute names as the ``Rule`` / ``RuleBinding``
ORM rows, so code that reads a rule (row checks, change detection, coverage)
accepts either.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass(frozen=True)
class ReferenceBinding:
    sirg_cd: Optional[str]
    sir_id: Optional[str]
    cmpt_nm: Optional[str]
    waived_if_whitelisted: bool
    waived_to_validate: bool
    check_service_code: Optional[str]
    attribute_ids: tuple[str, ...] = ()
    sirg_id: Optional[str] = None


@dataclass(frozen=True)
class ReferenceRule:
    """One baseline Import row. ``id`` is a stable reference key, not an app row id."""

    id: str
    row_no: Optional[int]
    direction: str
    region: Optional[str]
    ctry_cd: str
    shipment_type: Optional[str]
    effective_date: Optional[dt.date]
    expiry_date: Optional[dt.date]
    network_product_codes: Optional[str]
    value_basis: Optional[str]
    currency: Optional[str]
    min_value: Optional[float]
    max_value: Optional[float]
    min_weight: Optional[float]
    max_weight: Optional[float]
    other_logic: Optional[str]
    country_hold_cd: Optional[str]
    global_hold_cd: Optional[str]
    sirg_cd: Optional[str]
    doc_reference: Optional[str]
    bindings: tuple[ReferenceBinding, ...] = field(default_factory=tuple)

    @property
    def generated_doc_reference(self) -> str:
        return f"{self.ctry_cd}|{self.direction}|{self.country_hold_cd or ''}|{self.global_hold_cd or ''}"


@dataclass(frozen=True)
class MirrorSirRow:
    sir_id: str
    cmpt_nm: Optional[str]
    nm: Optional[str]
    dsc: Optional[str]


@dataclass(frozen=True)
class MirrorSirgRow:
    sirg_id: str
    sirg_cd: Optional[str]
    sirg_nm: Optional[str]
    sirg_dsc: Optional[str]
    ctry_cd: Optional[str]
    proc_lvl_cd: Optional[str]
    cmpt_nm: Optional[str]
    sir_id: Optional[str]


class ReferenceRepository(Protocol):
    """Read-only access to workbook reference data. Implementations never write."""

    source: str

    def workbook_version(self) -> Optional[str]:
        """Identifier of the reference data in use (workbook version or sirdb batch)."""

    def baseline_rules(self, country: Optional[str] = None) -> list[ReferenceRule]:
        """Baseline rows (with bindings) ordered by row number; all countries when ``country`` is None."""

    def permitted_values(self, version: Optional[str] = None) -> dict[str, set[str]]:
        """Validation lists by canonical field (region, shipment_type, value_basis, currency, waiver, country)."""

    def mirror_sir(self, version: Optional[str] = None) -> list[MirrorSirRow]:
        """The workbook's Technical SIR tab."""

    def mirror_sirg(self, country: Optional[str] = None, version: Optional[str] = None) -> list[MirrorSirgRow]:
        """The workbook's Technical SIRG tab, optionally for one country."""

    def expression_templates(self, version: Optional[str] = None) -> list[str]:
        """The Other Logic palette, in workbook order."""
