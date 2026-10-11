"""Structured outputs for the advisory layer.

Agents emit these and nothing else. Free-form prose cannot reach the rule model,
which is what keeps "AI recommends" true in code rather than in a policy doc.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Condition(BaseModel):
    """One extracted business condition, in the vocabulary of the rule layer."""

    field: str = Field(description="Condition subject, e.g. 'shipment_type', 'service_code', 'SDT'")
    operator: Literal["equals", "not_equals", "contains", "not_contains", "present", "absent",
                      "greater_or_equal", "less_or_equal"]
    value: Optional[str] = Field(default=None, description="Comparison value, omitted for present/absent")


class RequirementInterpretation(BaseModel):
    """The Requirement Interpreter's only output shape."""

    country_code: Optional[str] = Field(default=None, description="ISO-2 DHL country code, if stated")
    shipment_type: Optional[Literal["B2B", "B2C", "B2B/B2C"]] = None
    direction: Literal["Import", "Export"] = "Import"
    requirement_groups: list[str] = Field(
        default_factory=list,
        description="Requirement group codes the requirement asks for, e.g. ['IOSS', 'POAB']",
    )
    conditions: list[Condition] = Field(default_factory=list)
    expected_behaviour: Optional[str] = None
    ambiguities: list[str] = Field(
        default_factory=list,
        description="Statements that cannot be resolved without asking. Never guess into this gap.",
    )
    missing_information: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"
    reasoning: Optional[str] = Field(default=None, description="Why this reading, for the human reviewer")

    @property
    def needs_clarification(self) -> bool:
        return bool(self.ambiguities or self.missing_information) or self.confidence == "low"


class ProposedRule(BaseModel):
    """A candidate rule row. Deliberately mirrors the Rule model's own fields."""

    ctry_cd: str
    direction: Literal["Import", "Export"] = "Import"
    region: Optional[str] = None
    shipment_type: Optional[str] = None
    effective_date: Optional[dt.date] = None
    expiry_date: Optional[dt.date] = None
    network_product_codes: Optional[str] = None
    value_basis: Optional[str] = None
    currency: Optional[str] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    min_weight: Optional[float] = None
    max_weight: Optional[float] = None
    other_logic: Optional[str] = Field(
        default=None,
        description="Condition expression. Must parse under the platform grammar.",
    )
    country_hold_cd: Optional[str] = None
    global_hold_cd: Optional[str] = None
    sirg_cd: Optional[str] = Field(default=None, description="Requirement group code this rule raises")
    sir_id: Optional[str] = Field(default=None, description="Requirement definition id, if known")
    cmpt_nm: Optional[str] = None
    waived_to_validate: bool = False
    waived_if_whitelisted: bool = False
    rationale: Optional[str] = None


class ChangeSet(BaseModel):
    """A proposal, not a change.

    The platform stages this, validates it, and discards it unless a human
    accepts. It is never applied directly.
    """

    case_id: Optional[str] = None
    summary: str
    rules: list[ProposedRule] = Field(default_factory=list)
    reuses_existing: list[str] = Field(
        default_factory=list,
        description="Ids of existing rules or definitions reused instead of duplicated",
    )
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class TestCase(BaseModel):
    test_id: str
    scenario: str
    business_summary: Optional[str] = Field(
        default=None, description="One plain-language sentence the business team can review"
    )
    kind: Literal["positive", "negative", "boundary", "missing_data", "regression"]
    preconditions: list[str] = Field(default_factory=list)
    input_conditions: list[Condition] = Field(default_factory=list)
    expected_requirement: Optional[str] = Field(
        default=None, description="Requirement group code expected to be raised, or null for none"
    )
    expected_case_created: bool = True
    validation_criteria: Optional[str] = None
    rule_coverage: list[str] = Field(default_factory=list)
    priority: Literal["high", "medium", "low"] = "medium"


class TestCaseSuite(BaseModel):
    summary: str
    cases: list[TestCase] = Field(default_factory=list)
    uncovered_conditions: list[str] = Field(
        default_factory=list,
        description="Conditions the suite could not cover, stated rather than hidden",
    )


class FailureAnalysis(BaseModel):
    """RCA for one failed execution. Recommends; never edits."""

    test_id: str
    likely_cause: str
    category: Literal["payload", "rule_logic", "requirement_definition", "package_config",
                      "environment", "expected_result_wrong", "unknown"]
    evidence: list[str] = Field(default_factory=list)
    recommended_action: str
    change_rules: bool = Field(
        default=False,
        description="True only if the rule itself is wrong. Prefer checking test data first.",
    )
    confidence: Literal["high", "medium", "low"] = "medium"


# --------------------------------------------------------------------------- #
# v2: intake, timeline, UAT payloads and response review
# --------------------------------------------------------------------------- #

class BusinessRequirement(RequirementInterpretation):
    """The captured business requirement: the interpretation plus business facts."""

    summary: Optional[str] = Field(default=None, description="Two or three plain sentences")
    requested_rtp: Optional[dt.date] = Field(default=None, description="Requested go-live date")
    value_threshold: Optional[float] = None
    currency: Optional[str] = None
    business_owner: Optional[str] = None
    sample_scenarios: list[str] = Field(default_factory=list)


class IntakeTurn(BaseModel):
    """One reply of the intake chatbot."""

    reply: str = Field(description="What to show the user: a question, or the summary to confirm")
    complete: bool = Field(default=False, description="True only when every essential fact is known")
    requirement: Optional[BusinessRequirement] = None


class PlannedMilestone(BaseModel):
    stage: str
    start: dt.date
    end: dt.date
    notes: Optional[str] = None


class TimelinePlan(BaseModel):
    milestones: list[PlannedMilestone]
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class PayloadChange(BaseModel):
    path: str
    value: Any = None
    reason: Optional[str] = None


class GeneratedPayload(BaseModel):
    payload: dict[str, Any]
    changes: list[PayloadChange] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class ResponseReview(BaseModel):
    verdict: Literal["PASS", "FAIL", "INCONCLUSIVE"]
    reasons: list[str] = Field(default_factory=list)
    observed_requirements: list[str] = Field(default_factory=list)
    business_explanation: Optional[str] = Field(
        default=None, description="One sentence a business reviewer can understand"
    )
