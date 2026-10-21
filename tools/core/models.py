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
    Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, MetaData, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

#: PostgreSQL schema of the application tables (sirdb sits beside it; docs/adr/0003).
APP_SCHEMA = "app"


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    metadata = MetaData(schema=APP_SCHEMA)


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
    # 64, not 36: package 2.10.4-beta.2 ships one id with a stray trailing character (kept as written).
    derived_from_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
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
    # Optimistic lock (docs/adr/0003): every UPDATE checks and bumps it; a stale write
    # raises StaleDataError, which the API answers with 409.
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": row_version}

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
    # Optimistic lock (docs/adr/0003): every UPDATE checks and bumps it; a stale write
    # raises StaleDataError, which the API answers with 409.
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": row_version}

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
    state: Mapped[str] = mapped_column(String(32), default="INTAKE", index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    # The config package the case was configured on, pinned when the M2C draft starts,
    # so the case stays reproducible against that package (docs/adr/0003).
    package_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    package_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Optimistic lock (docs/adr/0003): every UPDATE checks and bumps it; a stale write
    # raises StaleDataError, which the API answers with 409.
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": row_version}

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


# --------------------------------------------------------------------------- #
# Users and access control
# --------------------------------------------------------------------------- #

class User(Base):
    """A platform user. ``role`` drives RBAC; ``countries`` scopes business users."""

    __tablename__ = "app_user"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    countries: Mapped[Any] = mapped_column(JSON, default=list)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    last_login_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)


# --------------------------------------------------------------------------- #
# Intake — the business requirement, captured by chat or by form + NLP
# --------------------------------------------------------------------------- #

class Requirement(Base):
    """One captured version of a case's business requirement."""

    __tablename__ = "requirement"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("onboarding_case.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    mode: Mapped[str] = mapped_column(String(8))  # CHAT | FORM
    text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    structured: Mapped[Any] = mapped_column(JSON, default=dict)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class IntakeMessage(Base):
    """One turn of the intake chatbot conversation."""

    __tablename__ = "intake_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    author: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


# --------------------------------------------------------------------------- #
# Timeline — AI-proposed from the PM questionnaire, approved by the PM
# --------------------------------------------------------------------------- #

class Timeline(Base):
    __tablename__ = "timeline"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("onboarding_case.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")  # DRAFT|APPROVED|SUPERSEDED
    answers: Mapped[Any] = mapped_column(JSON, default=dict)
    facts: Mapped[Any] = mapped_column(JSON, default=dict)
    assumptions: Mapped[Any] = mapped_column(JSON, default=list)
    risks: Mapped[Any] = mapped_column(JSON, default=list)
    open_questions: Mapped[Any] = mapped_column(JSON, default=list)
    at_risk: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    approved_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    approved_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    milestones: Mapped[list["Milestone"]] = relationship(
        back_populates="timeline", cascade="all, delete-orphan", order_by="Milestone.seq"
    )


class Milestone(Base):
    __tablename__ = "milestone"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    timeline_id: Mapped[str] = mapped_column(String(36), ForeignKey("timeline.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    owner: Mapped[str] = mapped_column(String(64))
    planned_start: Mapped[dt.date] = mapped_column(Date)
    planned_end: Mapped[dt.date] = mapped_column(Date)
    actual_start: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    actual_end: Mapped[Optional[dt.date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    timeline: Mapped["Timeline"] = relationship(back_populates="milestones")


# --------------------------------------------------------------------------- #
# UAT — test cases, sample payloads, runs and results
# --------------------------------------------------------------------------- #

class UatTestCase(Base):
    """A UAT test case derived from the case's M2C draft."""

    __tablename__ = "uat_test_case"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    rule_set_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    test_id: Mapped[str] = mapped_column(String(64))
    scenario: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    business_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preconditions: Mapped[Any] = mapped_column(JSON, default=list)
    input_conditions: Mapped[Any] = mapped_column(JSON, default=list)
    expected_requirement: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    expected_case_created: Mapped[bool] = mapped_column(Boolean, default=True)
    validation_criteria: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rule_coverage: Mapped[Any] = mapped_column(JSON, default=list)
    priority: Mapped[str] = mapped_column(String(8), default="medium")
    # DRAFT -> CCRE_APPROVED -> BUSINESS_APPROVED; REJECTED is excluded from execution
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    review_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    # Optimistic lock (docs/adr/0003): every UPDATE checks and bumps it; a stale write
    # raises StaleDataError, which the API answers with 409.
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    __mapper_args__ = {"version_id_col": row_version}


class PayloadTemplate(Base):
    """A sample request payload the generator adapts for each test case."""

    __tablename__ = "payload_template"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(128))
    country: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    body: Mapped[Any] = mapped_column(JSON)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class UatRun(Base):
    __tablename__ = "uat_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    rule_set_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    cycle: Mapped[int] = mapped_column(Integer, default=1)
    template_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    executor: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="RUNNING")
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    started_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    results: Mapped[list["UatResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class UatResult(Base):
    __tablename__ = "uat_result"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("uat_run.id"), index=True)
    test_case_id: Mapped[str] = mapped_column(String(36), index=True)
    test_id: Mapped[str] = mapped_column(String(64))
    payload: Mapped[Any] = mapped_column(JSON, default=dict)
    changes: Mapped[Any] = mapped_column(JSON, default=list)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Any] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    verdict: Mapped[str] = mapped_column(String(16))  # PASS | FAIL | ERROR | INCONCLUSIVE
    verdict_source: Mapped[str] = mapped_column(String(16))  # deterministic | ai
    check: Mapped[Any] = mapped_column(JSON, default=dict)
    review: Mapped[Any] = mapped_column(JSON, default=dict)
    analysis: Mapped[Any] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)

    run: Mapped["UatRun"] = relationship(back_populates="results")



# --------------------------------------------------------------------------- #
# Execution endpoints (Admin) and environment comparisons
# --------------------------------------------------------------------------- #

class ExecutionEndpoint(Base):
    """An API the UAT run calls (e.g. CRMS categorization TEST, CCRE UAT).

    The credential is stored encrypted (``secret_enc``) and is never returned to
    the browser. Response paths tell the checker where the endpoint reports what
    it raised, so pass/fail is decided by code for any response shape.
    """

    __tablename__ = "execution_endpoint"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    url: Mapped[str] = mapped_column(String(1024))
    method: Mapped[str] = mapped_column(String(8), default="POST")
    auth_header: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default="x-api-key")
    secret_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    secret_hint: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    extra_headers: Mapped[Any] = mapped_column(JSON, default=dict)
    timeout_seconds: Mapped[float] = mapped_column(Float, default=30.0)
    groups_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    case_flag_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status_ok_value: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    compare_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class UatComparison(Base):
    """The same request sent to a second environment, and how its response differs."""

    __tablename__ = "uat_comparison"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    result_id: Mapped[str] = mapped_column(String(36), index=True)
    endpoint_name: Mapped[str] = mapped_column(String(64))
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Any] = mapped_column(JSON, nullable=True)
    identical: Mapped[bool] = mapped_column(Boolean, default=False)
    summary: Mapped[Any] = mapped_column(JSON, default=dict)
    differences: Mapped[Any] = mapped_column(JSON, default=list)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


# --------------------------------------------------------------------------- #
# Email: settings, sent-mail log, DMG email template and per-case task
# --------------------------------------------------------------------------- #

class MailSettings(Base):
    """SMTP settings (one row). Without a host, mail goes to the outbox folder."""

    __tablename__ = "mail_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    port: Mapped[int] = mapped_column(Integer, default=587)
    security: Mapped[str] = mapped_column(String(8), default="starttls")  # starttls | ssl | none
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    password_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    from_address: Mapped[str] = mapped_column(String(255), default="ccre-onboarding@localhost")
    public_url: Mapped[str] = mapped_column(String(255), default="http://localhost:8000")
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Notification(Base):
    """Every email the platform sent (or put in the outbox)."""

    __tablename__ = "notification"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(24))  # REMINDER | DMG | TEST
    state: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    to: Mapped[Any] = mapped_column(JSON, default=list)
    cc: Mapped[Any] = mapped_column(JSON, default=list)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12))  # SENT | OUTBOX | FAILED
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sent_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)


class DmgTemplate(Base):
    """The DMG change email template and recipients — configured by the CCRE team."""

    __tablename__ = "dmg_template"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    to: Mapped[Any] = mapped_column(JSON, default=list)
    cc: Mapped[Any] = mapped_column(JSON, default=list)
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class DmgTask(Base):
    """One onboarding's DMG email: filled from the template, reviewed, then sent."""

    __tablename__ = "dmg_task"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    # DRAFT -> IN_REVIEW -> SENT (completed);  IN_REVIEW -> DRAFT on reject;  NOT_REQUIRED (completed)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT")
    subject: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    to: Mapped[Any] = mapped_column(JSON, default=list)
    cc: Mapped[Any] = mapped_column(JSON, default=list)
    prepared_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    submitted_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decided_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decision_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notification_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    sent_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# --------------------------------------------------------------------------- #
# Sanity check -- evidence that the configuration was checked before UAT
# --------------------------------------------------------------------------- #

class SanityRun(Base):
    """One run of the sanity checklist against the onboarding's configuration.

    ``fingerprint`` identifies exactly what was checked (M2C rows and bindings,
    requirement version, DMG status, package version, waivers). Approving the
    sanity check needs a passing run whose fingerprint still matches -- so any
    change after the run means it must run again.
    """

    __tablename__ = "sanity_run"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("onboarding_case.id"), index=True)
    rule_set_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    cycle: Mapped[int] = mapped_column(Integer, default=1)
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(8))           # PASS | FAIL
    passed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    waived: Mapped[int] = mapped_column(Integer, default=0)
    items: Mapped[Any] = mapped_column(JSON, default=list)  # the checklist as shown, with findings
    run_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now, index=True)


class SanityWaiver(Base):
    """A check accepted as an exception, with the reason (e.g. the Support ticket for a package gap)."""

    __tablename__ = "sanity_waiver"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("onboarding_case.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(32))        # only waivable checks: package, requirement_match
    reason: Mapped[str] = mapped_column(Text)
    reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)   # ticket / email ref
    waived_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    revoked_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    revoked_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)


# --------------------------------------------------------------------------- #
# Beta files (sir-configuration packages) uploaded by an admin
# --------------------------------------------------------------------------- #

class PackageUpload(Base):
    """One uploaded beta file: stored by its hash, reviewed, and — on an admin's decision — active.

    Exactly one upload is ACTIVE at a time; every check in the platform reads the
    active package. Uploads are never overwritten: a new file is a new row.
    """

    __tablename__ = "package_upload"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    size: Mapped[int] = mapped_column(Integer)
    stored_path: Mapped[str] = mapped_column(String(512))
    version: Mapped[str] = mapped_column(String(64), index=True)       # catalog key (package_version)
    declared_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)   # from CHANGELOG
    release_date: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # REVIEWED -> ACTIVE -> SUPERSEDED;  REVIEWED -> REJECTED
    status: Mapped[str] = mapped_column(String(16), default="REVIEWED", index=True)
    review: Mapped[Any] = mapped_column(JSON, default=dict)
    uploaded_by: Mapped[str] = mapped_column(String(255))
    uploaded_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_now)
    decided_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
