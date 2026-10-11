"""Request and response models for the HTTP API."""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from pydantic import BaseModel, Field


class CaseCreate(BaseModel):
    code: str = Field(description="Case reference, e.g. ONB-2026-BG-014")
    ctry_cd: str
    title: str
    gccp_ref: Optional[str] = None
    requirement_text: Optional[str] = None
    business_owner: Optional[str] = None
    priority: Optional[str] = None
    requested_rtp: Optional[dt.date] = None


class CaseOut(BaseModel):
    id: str
    code: str
    ctry_cd: str
    title: str
    gccp_ref: Optional[str]
    state: str
    requested_rtp: Optional[dt.date]
    approved_rtp: Optional[dt.date]
    created_at: dt.datetime


class ApprovedRtp(BaseModel):
    approved_rtp: dt.date
    actor: str


class TransitionRequest(BaseModel):
    name: str = Field(description="Transition name, e.g. support_signoff")
    actor: str
    role: str = Field(description="COUNTRY | PM | SUPPORT | SYSTEM")
    comment: Optional[str] = None
    rule_set_id: Optional[str] = Field(
        default=None,
        description="Rule set to gate on. Required for transitions that need clean validation.",
    )
    tests_total: int = 0
    tests_passed: int = 0
    tests_failed: int = 0


class TransitionOut(BaseModel):
    case_id: str
    state: str
    fired: str


class AvailableTransition(BaseModel):
    name: str
    target: str
    actor: str
    blocked_by: list[str] = Field(default_factory=list)


class BindingOut(BaseModel):
    id: str
    sirg_cd: Optional[str]
    sir_id: Optional[str]
    cmpt_nm: Optional[str]
    waived_if_whitelisted: bool
    waived_to_validate: bool
    check_service_code: Optional[str]
    attribute_ids: list[str] = Field(default_factory=list)


class RuleOut(BaseModel):
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
    generated_doc_reference: str
    bindings: list[BindingOut] = Field(default_factory=list)
    # Business-readable rendering of the rule, for the review screen.
    statement: Optional[str] = None


class RuleUpdate(BaseModel):
    """Partial update. Only supplied fields change."""

    other_logic: Optional[str] = None
    shipment_type: Optional[str] = None
    currency: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_weight: Optional[float] = None
    max_weight: Optional[float] = None
    effective_date: Optional[dt.date] = None
    expiry_date: Optional[dt.date] = None
    network_product_codes: Optional[str] = None
    country_hold_cd: Optional[str] = None
    global_hold_cd: Optional[str] = None
    actor: str = "unknown"


class BindingUpdate(BaseModel):
    waived_to_validate: Optional[bool] = None
    waived_if_whitelisted: Optional[bool] = None
    check_service_code: Optional[str] = None
    actor: str = "unknown"


class FindingOut(BaseModel):
    code: str
    severity: str
    where: str
    message: str
    evidence: Optional[str] = None
    subjects: list[str] = Field(default_factory=list)
    counts: dict[str, int] = Field(default_factory=dict)


class ValidationOut(BaseModel):
    clean: bool
    blocker_count: int
    caution_count: int
    info_count: int
    checks_run: list[str]
    findings: list[FindingOut]
    run_id: Optional[str] = None


class ExpressionCheck(BaseModel):
    expression: str


class IngestRequest(BaseModel):
    path: str
    version: Optional[str] = None
    case_id: Optional[str] = None


class ProposalOut(BaseModel):
    id: str
    case_id: str
    origin: str
    status: str
    rationale: Optional[str]
    payload: dict[str, Any]
    created_at: dt.datetime


class ProposalDecision(BaseModel):
    actor: str
    accept: bool
    comment: Optional[str] = None
    rule_set_id: Optional[str] = Field(
        default=None, description="Rule set to apply the proposal into when accepting."
    )


# --------------------------------------------------------------------------- #
# advisory (agent) endpoints
# --------------------------------------------------------------------------- #

class InterpretRequest(BaseModel):
    requirement_text: str = Field(min_length=1)
    actor: str = "anonymous"


class DraftRulesRequest(BaseModel):
    requirement_text: str = Field(default="", description="Original requirement, for context")
    interpretation: Optional[dict] = Field(
        default=None, description="An approved RequirementInterpretation, if one exists"
    )
    actor: str = "anonymous"


class DesignTestsRequest(BaseModel):
    country: Optional[str] = Field(default=None, description="Limit the suite to one country's rules")
    notes: str = ""
    actor: str = "anonymous"


class AnalyseFailureRequest(BaseModel):
    test_id: str = Field(min_length=1)
    expected: str = ""
    actual: str = ""
    details: str = Field(default="", description="Payload excerpt, logs, anything relevant")
    case_id: Optional[str] = None
    actor: str = "anonymous"


class ChatRequest(BaseModel):
    message: str = ""
    session_id: Optional[str] = None


# --------------------------------------------------------------------------- #
# v2: auth, admin, lifecycle
# --------------------------------------------------------------------------- #

class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class UserCreate(BaseModel):
    email: str = Field(min_length=3)
    name: str = Field(min_length=1)
    role: str
    password: str = Field(min_length=8)
    countries: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    active: Optional[bool] = None
    countries: Optional[list[str]] = None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8)


class OnboardingCreate(BaseModel):
    ctry_cd: str = Field(min_length=2, max_length=2)
    title: str = Field(min_length=1)
    code: Optional[str] = Field(default=None, description="Generated when omitted")
    gccp_ref: Optional[str] = None
    priority: Optional[str] = None


class LifecycleTransition(BaseModel):
    name: str
    comment: Optional[str] = None


class IntakeChat(BaseModel):
    message: str = Field(min_length=1)


class IntakeForm(BaseModel):
    description: str = Field(min_length=1, description="The requirement in the business team's own words")
    shipment_type: Optional[str] = None
    direction: Optional[str] = None
    requirement_groups: list[str] = Field(default_factory=list)
    requested_rtp: Optional[dt.date] = None
    value_threshold: Optional[float] = None
    currency: Optional[str] = None
    business_owner: Optional[str] = None


class TimelineAnswers(BaseModel):
    answers: dict[str, Any]


class MilestoneEdit(BaseModel):
    stage: str
    start: dt.date
    end: dt.date
    notes: Optional[str] = None


class MilestoneEdits(BaseModel):
    milestones: list[MilestoneEdit]


class M2CDraftRequest(BaseModel):
    notes: str = ""


class TestCaseReview(BaseModel):
    status: str = Field(description="REJECTED to exclude the case, DRAFT to restore it")
    comment: Optional[str] = None


class GenerateTestCases(BaseModel):
    notes: str = ""


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1)
    country: Optional[str] = None
    body: Any = Field(description="The sample payload: a JSON object, or a JSON string")
    notes: Optional[str] = None


class RunRequest(BaseModel):
    template_id: Optional[str] = None
