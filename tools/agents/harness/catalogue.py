"""The Tool catalogue (docs/design/agent-design.md, "Tool catalogue") on the registry.

Each catalogue tool is registered against the existing read function that backs
it -- nothing is reimplemented -- with the allow-list taken from the design
table (:data:`ALLOW_LISTS`). Tools with no backing function yet are listed in
:data:`CATALOGUE_GAPS` with the phase expected to add them; a test keeps the two
in step with the table.

Phase 1 builds the registry only. Agents keep their current ADK tool lists until
Phase 4 switches each one to ``get_tools_for(agent)``.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select

from .registry import AGENT_NAMES, CallScope, ToolRegistry

ALL = frozenset(AGENT_NAMES)
ORCH = "ccre_orchestrator"
INTAKE = "intake_assistant"
INTERP = "requirement_interpreter"
PLANNER = "timeline_planner"
DRAFTER = "rule_drafter"
DESIGNER = "test_case_designer"
PAYLOAD = "payload_generator"
REVIEWER = "response_reviewer"
ANALYST = "failure_analyst"

#: Allow-lists exactly as in the design's Tool catalogue table.
ALLOW_LISTS: dict[str, frozenset[str]] = {
    "get_case": ALL,
    "get_intake_fields": frozenset({INTAKE}),
    "get_picklist": frozenset({INTAKE}),
    "get_requirement_groups": frozenset({INTAKE, DRAFTER}),
    "get_requirement_bindings": frozenset({INTAKE, DRAFTER}),
    "search_m2c_rows": frozenset({INTERP, DRAFTER, ORCH}),
    "resolve_sir": frozenset({INTERP, DRAFTER, ANALYST, ORCH}),
    "get_package_definition": frozenset({INTERP, DRAFTER, ANALYST}),
    "package_coverage": frozenset({INTERP, DRAFTER, ANALYST}),
    "diff_package_versions": frozenset({INTERP, DRAFTER, ANALYST}),
    "check_condition": frozenset({INTAKE, DRAFTER, DESIGNER}),
    "check_other_logic": frozenset({INTAKE, DRAFTER, DESIGNER}),
    "explain_condition": frozenset({INTAKE, DRAFTER, DESIGNER}),
    "diff_against_workbook": frozenset({DRAFTER}),
    "get_baseline_plan": frozenset({PLANNER}),
    "get_calendar": frozenset({PLANNER}),
    "get_historical_stage_durations": frozenset({PLANNER}),
    "validate_plan": frozenset({PLANNER}),
    "get_rule_rows": frozenset({DESIGNER, REVIEWER, ANALYST}),
    "get_test_row": frozenset({DESIGNER, REVIEWER, ANALYST}),
    "get_existing_test_rows": frozenset({DESIGNER, REVIEWER, ANALYST}),
    "get_crms_fields": frozenset({PAYLOAD, DESIGNER}),
    "get_sample_payload": frozenset({PAYLOAD, DESIGNER}),
    "build_payload": frozenset({PAYLOAD, DESIGNER}),
    "validate_payload": frozenset({PAYLOAD, DESIGNER}),
    "get_payload": frozenset({REVIEWER, ANALYST, ORCH}),
    "get_response": frozenset({REVIEWER, ANALYST, ORCH}),
    "compare_envs": frozenset({REVIEWER, ANALYST, ORCH}),
    "get_cycle_history": frozenset({REVIEWER, ANALYST, ORCH}),
    "get_audit_history": frozenset({ORCH}),
}

#: Catalogue tools with no backing read function yet, and when they are expected.
CATALOGUE_GAPS: dict[str, str] = {
    "get_requirement_bindings": "Rule-row bindings per package version; Phase 2 (sirdb repository).",
    "diff_package_versions": "Needs two loaded package versions side by side; Phase 2.",
    "explain_condition": "Branch enumeration over the grammar AST; Phase 4 (test_case_designer).",
    "get_calendar": "Country blackout calendar store does not exist; blackouts come only from PM answers. Phase 4.",
    "get_historical_stage_durations": "Stage durations from the audit trail; Phase 4 (timeline_planner).",
    "get_rule_rows": "Accepted rule rows per case; Phase 4 (test_case_designer).",
    "get_test_row": "Single UAT row read; Phase 4 (response_reviewer / failure_analyst).",
    "get_existing_test_rows": "UAT rows per case; Phase 4 (test_case_designer).",
    "get_crms_fields": "CRMS field catalogue with types and allowed values does not exist; Phase 4 (payload_generator).",
    "get_payload": "Payload by hash needs the payload store; Phase 3/4.",
    "get_response": "Response by run id needs evidence storage reads; Phase 3/4.",
    "get_cycle_history": "Failures and fixes per UAT cycle; Phase 4 (failure_analyst).",
}


# --------------------------------------------------------------------------- #
# input models
# --------------------------------------------------------------------------- #

class CaseRef(BaseModel):
    case_id: str = Field(min_length=1)


class CountryArg(BaseModel):
    country_code: str = Field(min_length=2, max_length=4)


class PicklistArgs(CountryArg):
    field: str = Field(min_length=1)


class SearchRowsArgs(CountryArg):
    requirement_group: str = ""
    shipment_type: str = ""


class ResolveSirArgs(CountryArg):
    sirg_cd: str = Field(min_length=1)
    processing_type: str = "IMP_CLR"


class SirIdArgs(BaseModel):
    sir_id: str = Field(min_length=1)


class ExpressionArgs(BaseModel):
    expression: str


class BaselineArgs(CaseRef):
    answers: dict[str, Any]


class PlanArgs(BaseModel):
    milestones: list[dict[str, Any]]
    answers: dict[str, Any]


class NoArgs(BaseModel):
    pass


class BuildPayloadArgs(CountryArg):
    sample: dict[str, Any]
    test_case: dict[str, Any]
    direction: str = "Import"


class ValidatePayloadArgs(BaseModel):
    payload: dict[str, Any]
    country_code: Optional[str] = None
    direction: Optional[str] = None


class CompareArgs(BaseModel):
    body_a: Any
    body_b: Any
    path: Optional[str] = None


class AuditArgs(CaseRef):
    limit: int = Field(default=50, ge=1, le=200)


# --------------------------------------------------------------------------- #
# backing functions (thin adapters over existing modules)
# --------------------------------------------------------------------------- #

def _case_country(args: Any) -> Optional[str]:
    from tools.core.db import session_scope
    from tools.core.models import OnboardingCase

    with session_scope() as session:
        case = session.get(OnboardingCase, args.case_id)
        return case.ctry_cd if case else None


def _load_case(session: Any, case_id: str) -> Any:
    from tools.core.models import OnboardingCase

    case = session.get(OnboardingCase, case_id)
    if case is None:
        raise LookupError(f"No onboarding case {case_id}.")
    return case


def _get_case(args: CaseRef, scope: CallScope) -> dict[str, Any]:
    from tools.core.db import session_scope

    with session_scope() as session:
        case = _load_case(session, args.case_id)
        return {
            "id": case.id, "code": case.code, "country": case.ctry_cd, "title": case.title,
            "state": case.state, "priority": case.priority,
            "requested_rtp": case.requested_rtp.isoformat() if case.requested_rtp else None,
            "approvals": [{"stage": a.stage, "decision": a.decision, "role": a.role, "at": a.at.isoformat()}
                          for a in sorted(case.approvals, key=lambda a: a.at)[-10:]],
        }


def _get_intake_fields(args: CountryArg, scope: CallScope) -> list[dict[str, Any]]:
    from tools import intake_fields
    from tools.core.db import session_scope

    with session_scope() as session:
        return intake_fields.field_specs(intake_fields.load_options(session, args.country_code.upper()))


def _get_picklist(args: PicklistArgs, scope: CallScope) -> dict[str, Any]:
    from tools import intake_fields
    from tools.core.db import session_scope

    with session_scope() as session:
        options = intake_fields.load_options(session, args.country_code.upper())
    key = "currency_all" if args.field == "currency" else args.field
    if key not in options or not isinstance(options[key], list):
        raise LookupError(f"Field {args.field!r} has no pick-list.")
    return {"field": args.field, "values": options[key]}


def _get_requirement_groups(args: CountryArg, scope: CallScope) -> dict[str, Any]:
    from tools import intake_fields
    from tools.core.db import session_scope

    with session_scope() as session:
        codes, details, version = intake_fields.package_groups(session, args.country_code.upper())
    return {"package_version": version, "groups": details}


def _search_m2c_rows(args: SearchRowsArgs, scope: CallScope) -> dict[str, Any]:
    from tools.functions import find_similar_rules

    return find_similar_rules(args.country_code, args.requirement_group, args.shipment_type)


def _resolve_sir(args: ResolveSirArgs, scope: CallScope) -> dict[str, Any]:
    from tools.sirdb.db import connect
    from tools.sirdb.resolve import resolve_sirg

    with connect(actor=f"agent-tool:{scope.user_id}") as conn, conn.cursor() as cur:
        return resolve_sirg(cur, args.country_code.upper(), args.sirg_cd.upper(), args.processing_type).as_dict()


def _get_package_definition(args: SirIdArgs, scope: CallScope) -> dict[str, Any]:
    from tools.functions import get_requirement_definition

    return get_requirement_definition(args.sir_id)


def _package_coverage(args: CountryArg, scope: CallScope) -> dict[str, Any]:
    from tools.functions import country_package_status

    return country_package_status(args.country_code)


def _check_expression(args: ExpressionArgs, scope: CallScope) -> dict[str, Any]:
    from tools.core import grammar
    from tools.functions import check_expression

    return {**check_expression(args.expression), "gate": grammar.gate_other_logic(args.expression).model_dump()}


def _diff_against_workbook(args: CaseRef, scope: CallScope) -> dict[str, Any]:
    from tools import ruleconfig
    from tools.core.db import session_scope
    from tools.workflow.case_facts import baseline_rule_set, case_rule_set

    with session_scope() as session:
        case = _load_case(session, args.case_id)
        draft = case_rule_set(session, case)
        if draft is None:
            return {"draft": None, "changes": []}
        baseline = baseline_rule_set(session, case.ctry_cd)
        return {"draft": draft.version,
                "changes": ruleconfig.changes(session, draft, baseline, case.ctry_cd)}


def _get_baseline_plan(args: BaselineArgs, scope: CallScope) -> dict[str, Any]:
    from tools.core.db import session_scope
    from tools.timeline import complexity_facts, estimate, normalise_answers
    from tools.workflow.case_facts import case_rule_set, latest_requirement

    answers = normalise_answers(args.answers)
    with session_scope() as session:
        case = _load_case(session, args.case_id)
        req = latest_requirement(session, case.id)
        rs = case_rule_set(session, case)
        facts = complexity_facts(session, case.ctry_cd, req.structured if req else {}, rs.id if rs else None)
    return {"facts": facts, "baseline": estimate(facts, answers)}


def _validate_plan(args: PlanArgs, scope: CallScope) -> dict[str, Any]:
    from tools.timeline.planning import gate_plan

    return gate_plan(args.milestones, args.answers).model_dump()


def _get_sample_payload(args: NoArgs, scope: CallScope) -> dict[str, Any]:
    from tools.execution import builtin_sample_payload

    return builtin_sample_payload()


def _build_payload(args: BuildPayloadArgs, scope: CallScope) -> dict[str, Any]:
    from tools.execution.crms import build_crms_payload

    return build_crms_payload(args.sample, args.test_case, args.country_code, args.direction)


def _validate_payload(args: ValidatePayloadArgs, scope: CallScope) -> dict[str, Any]:
    from tools.execution.crms import validate_crms_payload

    return validate_crms_payload(args.payload, args.country_code, args.direction).model_dump()


def _compare_envs(args: CompareArgs, scope: CallScope) -> dict[str, Any]:
    from tools.execution.crms import compare_responses

    return compare_responses(args.body_a, args.body_b, args.path)


def _get_audit_history(args: AuditArgs, scope: CallScope) -> list[dict[str, Any]]:
    from tools.core.db import session_scope
    from tools.core.models import AuditEvent

    with session_scope() as session:
        _load_case(session, args.case_id)
        events = session.execute(select(AuditEvent).where(AuditEvent.case_id == args.case_id)
                                 .order_by(AuditEvent.at.desc()).limit(args.limit)).scalars()
        return [{"at": e.at.isoformat(), "actor": e.actor, "action": e.action, "detail": e.detail} for e in events]


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #

Json = dict[str, Any]


def build_registry() -> ToolRegistry:
    reg = ToolRegistry()

    def add(name: str, description: str, input_model: type[BaseModel], output_type: Any, fn: Any,
            backed_by: str, **scope_rule: Any) -> None:
        reg.register(name=name, description=description, input_model=input_model, output_type=output_type,
                     fn=fn, agents=ALLOW_LISTS[name], backed_by=backed_by, **scope_rule)

    add("get_case", "Case summary: stage, country, approvals.", CaseRef, Json, _get_case,
        "app schema (OnboardingCase, Approval)", country_resolver=_case_country)
    add("get_intake_fields", "Required M2C Import columns with accepted values.", CountryArg, list[Json],
        _get_intake_fields, "tools.intake_fields.field_specs", country_arg="country_code")
    add("get_picklist", "Accepted values for one intake field.", PicklistArgs, Json, _get_picklist,
        "tools.intake_fields.load_options", country_arg="country_code")
    add("get_requirement_groups", "Requirement groups and definitions the active package maps for a country.",
        CountryArg, Json, _get_requirement_groups, "tools.intake_fields.package_groups",
        country_arg="country_code")
    add("search_m2c_rows", "Live Import rows by country / requirement group / shipment type.", SearchRowsArgs,
        Json, _search_m2c_rows, "tools.functions.find_similar_rules (app rule tables; sirdb in Phase 2)",
        country_arg="country_code")
    add("resolve_sir", "SIR/SIRG resolution and references from sirdb.", ResolveSirArgs, Json, _resolve_sir,
        "tools.sirdb.resolve.resolve_sirg", country_arg="country_code")
    add("get_package_definition", "One requirement definition and its attributes (package catalogue).",
        SirIdArgs, Json, _get_package_definition, "tools.functions.get_requirement_definition",
        country_neutral=True)
    add("package_coverage", "Whether the active package maps a country, and which groups.", CountryArg, Json,
        _package_coverage, "tools.functions.country_package_status (country level)", country_arg="country_code")
    add("check_condition", "Grammar verdict for a condition expression, with GateResult.", ExpressionArgs, Json,
        _check_expression, "tools.functions.check_expression + grammar.gate_other_logic", country_neutral=True)
    add("check_other_logic", "Grammar verdict for Other Logic, with GateResult.", ExpressionArgs, Json,
        _check_expression, "tools.functions.check_expression + grammar.gate_other_logic", country_neutral=True)
    add("diff_against_workbook", "Cell-level changes of the case's draft against the workbook.", CaseRef, Json,
        _diff_against_workbook, "tools.ruleconfig.changes", country_resolver=_case_country)
    add("get_baseline_plan", "Deterministic 7-milestone baseline for a case.", BaselineArgs, Json,
        _get_baseline_plan, "tools.timeline.complexity_facts + estimate", country_resolver=_case_country)
    add("validate_plan", "Plan gate verdict as a GateResult.", PlanArgs, Json, _validate_plan,
        "tools.timeline.planning.gate_plan", country_neutral=True)
    add("get_sample_payload", "The built-in sample payload.", NoArgs, Json, _get_sample_payload,
        "tools.execution.builtin_sample_payload (endpoint samples in Phase 4)", country_neutral=True)
    add("build_payload", "Adapt a ShpPcdDetailsMsg sample to one test case (code fills the template).",
        BuildPayloadArgs, Json, _build_payload, "tools.execution.crms.build_crms_payload",
        country_arg="country_code")
    add("validate_payload", "Structural CRMS payload verdict as a GateResult.", ValidatePayloadArgs, Json,
        _validate_payload, "tools.execution.crms.validate_crms_payload", country_neutral=True)
    add("compare_envs", "Differences between two environments' responses.", CompareArgs, Json, _compare_envs,
        "tools.execution.crms.compare_responses (bodies passed in; by test row in Phase 4)",
        country_neutral=True)
    add("get_audit_history", "Decisions on a case with actor and reason.", AuditArgs, list[Json],
        _get_audit_history, "app schema (AuditEvent)", country_resolver=_case_country)
    return reg


@lru_cache(maxsize=1)
def default_registry() -> ToolRegistry:
    return build_registry()
