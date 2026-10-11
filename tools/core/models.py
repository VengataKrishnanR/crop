"""Relational model.

Two distinct bodies of data live here and must not be conflated:

* **Catalog** -- ingested from the GCCP ``sir-configuration`` package. This is the
  source of truth. Nothing in the platform may write it; it is replaced wholesale
  by ingesting a newer package version.
* **Rules** -- the rule layer the platform authors and owns, which *references*
  the catalog by id. Rule sets are immutable once sealed; a change forks a new one.

The ``Mirror*`` tables hold the M2C workbook's own copy of the catalog. They exist
only so drift between the workbook and the package can be measured during
migration, and they are never used as an authority.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Optional

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------- #
# Catalog -- from the config package. Read-only to the platform.
# --------------------------------------------------------------------------- #

class ConfigPackage(Base):
    __tablename__ = "config_package"

    version: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(255))
    ingested_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    sirg_count: Mapped[int] = mapped_column(Integer, default=0)
    sir_count: Mapped[int] = mapped_column(Integer, default=0)
    mapping_count: Mapped[int] = mapped_column(Integer, default=0)
    release_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SirgDef(Base):
    """Shipment Information Requirement Group -- the document-type catalogue."""

    __tablename__ = "sirg_def"

    # Composite key: the same upstream id exists in every package version, and
    # holding two versions side by side is how a GCCP update gets reviewed.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    package_version: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    cd: Mapped[str] = mapped_column(String(16), index=True)
    nm: Mapped[str] = mapped_column(String(255))
    dsc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class SirDef(Base):
    """Shipment Information Requirement -- one document/data requirement definition."""

    __tablename__ = "sir_def"

    # Composite key, as for SirgDef: two package versions coexist so an incoming
    # GCCP release can be diffed against the one in CCRE before it is accepted.
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    package_version: Mapped[str] = mapped_column(String(64), primary_key=True, index=True)
    nm: Mapped[str] = mapped_column(String(255))
    dsc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cmpt_nm: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    cmpt_ty: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ctry_cd: Mapped[Optional[str]] = mapped_column(String(4), nullable=True, index=True)
    derived_from_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    sensitivity: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    apply_all: Mapped[bool] = mapped_column(Boolean, default=False)


class SirAttribute(Base):
    """A single attribute inside a SIR definition.

    ``Ent[]`` nests recursively (observed to 7 levels), so the tree is flattened
    with ``ent_path`` preserving where the attribute sat. ``msg_positions`` keeps
    the ``AttMsgPos`` entries verbatim -- these are what make deterministic DMG
    payload generation possible without a model inventing structure.

    ``att_id`` is **not** globally unique: definitions derived from one another
    can reuse their parent's attribute ids, so identity is ``(sir_id, att_id)``.
    Measured on package 2.10.4-beta.2 -- 8783 distinct ids, two of them shared by
    two definitions each, none repeated inside a single definition.
    """

    __tablename__ = "sir_attribute"
    __table_args__ = (
        UniqueConstraint("sir_id", "att_id", "package_version", name="uq_sir_attribute"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    att_id: Mapped[str] = mapped_column(String(36), index=True)
    sir_id: Mapped[str] = mapped_column(String(36), index=True)
    package_version: Mapped[str] = mapped_column(String(64), index=True)
    ent_path: Mapped[str] = mapped_column(String(512))
    nm: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    att_ty: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, default=False)
    msg_positions: Mapped[Any] = mapped_column(JSON, default=list)


class CtryProcMapping(Base):
    """country + processing level -> SIRG -> SIR.

    Reachability through this table is the *only* definition of an active SIR:
    the package carries no status field, so a definition nobody maps is inactive.
    """

    __tablename__ = "ctry_proc_mapping"
    __table_args__ = (
        UniqueConstraint(
            "ctry_cd", "proc_lvl_cd", "sirg_id", "sir_id", "package_version", name="uq_mapping",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ctry_cd: Mapped[str] = mapped_column(String(4), index=True)
    proc_lvl_cd: Mapped[str] = mapped_column(String(16))
    sirg_id: Mapped[str] = mapped_column(String(36), index=True)
    sir_id: Mapped[str] = mapped_column(String(36), index=True)
    package_version: Mapped[str] = mapped_column(String(64), index=True)


class ReleaseNoteEntry(Base):
    """A ctry / SIRG code / definition triple claimed by the package release notes."""

    __tablename__ = "release_note_entry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ctry_cd: Mapped[str] = mapped_column(String(4))
    sirg_cd: Mapped[str] = mapped_column(String(16))
    sir_id: Mapped[str] = mapped_column(String(36))
    package_version: Mapped[str] = mapped_column(String(64), index=True)


# --------------------------------------------------------------------------- #
# Workbook mirror -- migration-time only, never an authority
# --------------------------------------------------------------------------- #

class MirrorSir(Base):
    __tablename__ = "mirror_sir"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sir_id: Mapped[str] = mapped_column(String(36), index=True)
    cmpt_nm: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    nm: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dsc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_version: Mapped[str] = mapped_column(String(64), index=True)


class MirrorSirg(Base):
    __tablename__ = "mirror_sirg"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sirg_id: Mapped[str] = mapped_column(String(36), index=True)
    sirg_cd: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sirg_nm: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sirg_dsc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ctry_cd: Mapped[Optional[str]] = mapped_column(String(4), index=True)
    proc_lvl_cd: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    cmpt_nm: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    sir_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    source_version: Mapped[str] = mapped_column(String(64), index=True)


class PermittedValue(Base):
    """Allowed values per field, from the workbook's Validation tab."""

    __tablename__ = "permitted_value"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    field: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[str] = mapped_column(String(64))
    source_version: Mapped[str] = mapped_column(String(64))


class ExpressionTemplate(Base):
    """The workbook's Other Logic palette, kept so authors can pick instead of retype."""

    __tablename__ = "expression_template"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expression: Mapped[str] = mapped_column(Text)
    source_version: Mapped[str] = mapped_column(String(64))


# --------------------------------------------------------------------------- #
# Rules -- owned and authored by the platform
# --------------------------------------------------------------------------- #

class RuleSet(Base):
    """An immutable, versioned collection of rules belonging to one case."""

    __tablename__ = "rule_set"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("onboarding_case.id"), nullable=True, index=True)
    version: Mapped[str] = mapped_column(String(16))
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sealed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    created_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    source_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    rules: Mapped[list["Rule"]] = relationship(back_populates="rule_set", cascade="all, delete-orphan")
    case: Mapped[Optional["OnboardingCase"]] = relationship(back_populates="rule_sets")


class Rule(Base):
    """One rule row: the conditions under which a requirement group is raised."""

    __tablename__ = "rule"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rule_set_id: Mapped[str] = mapped_column(String(36), ForeignKey("rule_set.id"), index=True)
    row_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    direction: Mapped[str] = mapped_column(String(16), default="Import")
    region: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    ctry_cd: Mapped[str] = mapped_column(String(4), index=True)
    shipment_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    effective_date: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    expiry_date: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    network_product_codes: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    value_basis: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    min_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    min_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    other_logic: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    country_hold_cd: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    global_hold_cd: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sirg_cd: Mapped[Optional[str]] = mapped_column(String(16), index=True)
    doc_reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    rule_set: Mapped["RuleSet"] = relationship(back_populates="rules")
    bindings: Mapped[list["RuleBinding"]] = relationship(back_populates="rule", cascade="all, delete-orphan")

    @property
    def generated_doc_reference(self) -> str:
        """The key the workbook's CONCATENATE formula would produce.

        Regenerating this on export is what removes the hand-typed-key defect
        class -- row order stops being load-bearing.
        """
        return f"{self.ctry_cd}|{self.direction}|{self.country_hold_cd or ''}|{self.global_hold_cd or ''}"


class RuleBinding(Base):
    """Binds a rule to the requirement definition it raises."""

    __tablename__ = "rule_binding"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rule_id: Mapped[str] = mapped_column(String(36), ForeignKey("rule.id"), index=True)
    sirg_cd: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    sirg_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    sir_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    cmpt_nm: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    waived_if_whitelisted: Mapped[bool] = mapped_column(Boolean, default=False)
    waived_to_validate: Mapped[bool] = mapped_column(Boolean, default=False)
    check_service_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    attribute_ids: Mapped[Any] = mapped_column(JSON, default=list)

    rule: Mapped["Rule"] = relationship(back_populates="bindings")


# --------------------------------------------------------------------------- #
# Cases, approvals, audit
# --------------------------------------------------------------------------- #

class OnboardingCase(Base):
    __tablename__ = "onboarding_case"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    ctry_cd: Mapped[str] = mapped_column(String(4), index=True)
    title: Mapped[str] = mapped_column(String(255))
    gccp_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    requirement_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_owner: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    priority: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # Requested, approved and actual production dates are deliberately separate:
    # reaching a date never causes a release.
    requested_rtp: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    approved_rtp: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    actual_rtp: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    state: Mapped[str] = mapped_column(String(32), default="DRAFT", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    rule_sets: Mapped[list["RuleSet"]] = relationship(back_populates="case")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class Approval(Base):
    __tablename__ = "approval"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("onboarding_case.id"), index=True)
    stage: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32))
    decision: Mapped[str] = mapped_column(String(16))
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rule_set_version: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    case: Mapped["OnboardingCase"] = relationship(back_populates="approvals")


class AuditEvent(Base):
    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    actor: Mapped[str] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[Any] = mapped_column(JSON, default=dict)


class ValidationRun(Base):
    __tablename__ = "validation_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    rule_set_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    blocker_count: Mapped[int] = mapped_column(Integer, default=0)
    caution_count: Mapped[int] = mapped_column(Integer, default=0)
    info_count: Mapped[int] = mapped_column(Integer, default=0)
    findings: Mapped[Any] = mapped_column(JSON, default=list)


class ProposedChange(Base):
    """An advisory change-set.

    Agent output lands here and nowhere else. It carries no authority: it must be
    validated, then accepted by a human, before any rule row is written.
    """

    __tablename__ = "proposed_change"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    origin: Mapped[str] = mapped_column(String(32))  # agent name, or "human"
    payload: Mapped[Any] = mapped_column(JSON)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="PROPOSED")  # PROPOSED|ACCEPTED|REJECTED
    validation_run_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
