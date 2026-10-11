"""FunctionTools exposed to the CCRE agents.

Every tool is read-only except :func:`stage_change_set`, which writes to the
staging table alone and is called by the server, never handed to an agent. No tool can write a rule, approve anything, move a case, or
reach CCRE. That is the tool boundary from the brief, enforced by what exists
here rather than by instructions in a prompt.

Each tool is a plain function, so it is unit-testable without a model.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, select

from tools.core import grammar
from tools.core.db import session_scope
from tools.core.models import (
    ConfigPackage, CtryProcMapping, OnboardingCase, ProposedChange, Rule, RuleSet, SirAttribute,
    SirDef, SirgDef,
)
from tools.validation import load_snapshot, run_checks

MAX_ROWS = 40


def list_requirement_groups(country_code: str = "") -> dict[str, Any]:
    """List requirement groups (SIRG) from the config package catalogue.

    Args:
        country_code: Optional ISO-2 DHL country code. When given, only groups
            already configured for that country are returned.

    Returns:
        A dict with ``groups``: code, name and id for each group.
    """
    with session_scope() as session:
        if country_code:
            stmt = (
                select(SirgDef.cd, SirgDef.nm, SirgDef.id)
                .join(CtryProcMapping, CtryProcMapping.sirg_id == SirgDef.id)
                .where(CtryProcMapping.ctry_cd == country_code.upper())
                .distinct()
            )
        else:
            stmt = select(SirgDef.cd, SirgDef.nm, SirgDef.id).distinct()
        rows = session.execute(stmt.order_by(SirgDef.cd)).all()
        return {
            "country_code": country_code.upper() or None,
            "count": len(rows),
            "groups": [{"code": r[0], "name": r[1], "id": r[2]} for r in rows[:200]],
        }


def find_similar_rules(
    country_code: str = "", requirement_group: str = "", shipment_type: str = ""
) -> dict[str, Any]:
    """Find existing rules resembling the one being drafted, to encourage reuse.

    This is a structured query, not a similarity model: the rule layer is small
    and fully keyed, so exact filters beat embeddings here.

    Args:
        country_code: ISO-2 country code to match, or empty for any.
        requirement_group: Requirement group code (e.g. "IOSS"), or empty for any.
        shipment_type: "B2B", "B2C" or empty for any.

    Returns:
        A dict with ``rules``: the matching rules and their condition expressions.
    """
    with session_scope() as session:
        stmt = select(Rule)
        if country_code:
            stmt = stmt.where(Rule.ctry_cd == country_code.upper())
        if requirement_group:
            stmt = stmt.where(Rule.sirg_cd == requirement_group.upper())
        if shipment_type:
            stmt = stmt.where(Rule.shipment_type == shipment_type)
        rules = list(session.execute(stmt.limit(MAX_ROWS)).scalars())
        return {
            "count": len(rules),
            "rules": [
                {
                    "id": r.id,
                    "country": r.ctry_cd,
                    "requirement_group": r.sirg_cd,
                    "shipment_type": r.shipment_type,
                    "currency": r.currency,
                    "min_value": r.min_value,
                    "max_value": r.max_value,
                    "other_logic": r.other_logic,
                }
                for r in rules
            ],
        }


def get_requirement_definition(sir_id: str) -> dict[str, Any]:
    """Fetch one requirement definition and its attributes.

    Args:
        sir_id: The requirement definition UUID.

    Returns:
        The definition's metadata plus every attribute, including the DMG message
        positions that drive payload generation.
    """
    with session_scope() as session:
        version = session.execute(
            select(ConfigPackage.version).order_by(ConfigPackage.ingested_at.desc()).limit(1)
        ).scalar_one_or_none()
        sir = session.execute(
            select(SirDef).where(SirDef.id == sir_id, SirDef.package_version == version)
        ).scalar_one_or_none()
        if sir is None:
            return {"found": False, "sir_id": sir_id}
        attributes = list(session.execute(
            select(SirAttribute)
            .where(SirAttribute.sir_id == sir_id, SirAttribute.package_version == version)
        ).scalars())
        return {
            "found": True,
            "id": sir.id,
            "name": sir.nm,
            "description": sir.dsc,
            "component": sir.cmpt_nm,
            "country": sir.ctry_cd,
            "derived_from": sir.derived_from_id,
            "sensitivity": sir.sensitivity,
            "attributes": [
                {
                    "id": a.att_id,
                    "name": a.nm,
                    "type": a.att_ty,
                    "mandatory": a.is_mandatory,
                    "path": a.ent_path,
                    "message_positions": a.msg_positions,
                }
                for a in attributes[:60]
            ],
        }


def check_expression(expression: str) -> dict[str, Any]:
    """Parse and statically check a condition expression before proposing it.

    Args:
        expression: An ``Other Logic`` expression, e.g.
            ``!serviceCodeList.contains("DD")``.

    Returns:
        ``parses``, the ``normalised`` form, and any ``diagnostics``. Call this
        before putting an expression in a change-set.
    """
    diagnostics = grammar.analyse(expression)
    parses = not any(d.code == "EXPR_PARSE" for d in diagnostics)
    normalised: Optional[str] = None
    if parses:
        try:
            normalised = grammar.normalise(expression)
        except grammar.ExpressionError:
            parses = False
    return {
        "expression": expression,
        "parses": parses,
        "normalised": normalised,
        "errors": [d.message for d in diagnostics if d.severity == "error"],
        "warnings": [d.message for d in diagnostics if d.severity == "warning"],
        "known_functions": sorted(grammar.KNOWN_FUNCTIONS),
        "known_lists": sorted(grammar.KNOWN_METHODS),
        "known_fields": sorted(grammar.KNOWN_FIELDS),
    }


def country_package_status(country_code: str) -> dict[str, Any]:
    """Report whether the config package covers a country.

    Args:
        country_code: ISO-2 DHL country code.

    Returns:
        Mapping counts and the groups configured. A country with no mappings
        cannot be tested until Support rebuilds the package.
    """
    code = country_code.upper()
    with session_scope() as session:
        rows = list(session.execute(
            select(CtryProcMapping).where(CtryProcMapping.ctry_cd == code)
        ).scalars())
        groups = session.execute(
            select(SirgDef.cd)
            .join(CtryProcMapping, CtryProcMapping.sirg_id == SirgDef.id)
            .where(CtryProcMapping.ctry_cd == code)
            .distinct()
        ).scalars()
        return {
            "country_code": code,
            "mapping_rows": len(rows),
            "in_package": bool(rows),
            "configured_groups": sorted(g for g in groups),
            "note": (
                "Country absent from the package: a rebuild is required before testing."
                if not rows else "Country is configured in the package."
            ),
        }


def validate_rule_set(rule_set_id: str) -> dict[str, Any]:
    """Run the deterministic check register against a rule set.

    Args:
        rule_set_id: The rule set to validate.

    Returns:
        The full validation report. Blocking findings cannot be waived by any
        agent or user; they have to be fixed.
    """
    with session_scope() as session:
        snapshot = load_snapshot(session, rule_set_id=rule_set_id)
        report = run_checks(snapshot)
        return report.as_dict()


def list_rule_sets(country_code: str = "") -> dict[str, Any]:
    """List rule sets and onboarding cases so other tools can be given real ids.

    Args:
        country_code: Optional ISO-2 country code. When given, only rule sets that
            contain at least one rule for that country are returned.

    Returns:
        ``rule_sets`` (id, version, sealed, rule count) newest first, and the open
        onboarding ``cases`` (id, code, country, state).
    """
    with session_scope() as session:
        stmt = select(RuleSet).order_by(RuleSet.created_at.desc())
        sets = list(session.execute(stmt.limit(MAX_ROWS)).scalars())
        out = []
        for rs in sets:
            count_stmt = select(func.count()).select_from(Rule).where(Rule.rule_set_id == rs.id)
            if country_code:
                count_stmt = count_stmt.where(Rule.ctry_cd == country_code.upper())
            count = session.execute(count_stmt).scalar_one()
            if country_code and not count:
                continue
            out.append({"id": rs.id, "version": rs.version, "sealed": rs.sealed, "rules": count})
        case_stmt = select(OnboardingCase).order_by(OnboardingCase.created_at.desc())
        if country_code:
            case_stmt = case_stmt.where(OnboardingCase.ctry_cd == country_code.upper())
        cases = list(session.execute(case_stmt.limit(MAX_ROWS)).scalars())
        return {
            "rule_sets": out,
            "cases": [
                {"id": c.id, "code": c.code, "country": c.ctry_cd, "state": c.state, "title": c.title}
                for c in cases
            ],
        }


def stage_change_set(case_id: str, change_set_json: str, origin: str = "agent") -> dict[str, Any]:
    """Stage a proposed change-set and validate it. Does not apply anything.

    The proposal is written to the staging table, never to the rule tables. A
    human must accept it afterwards; until then it has no effect.

    Args:
        case_id: The onboarding case the proposal belongs to.
        change_set_json: A JSON ChangeSet document.
        origin: Which agent produced it.

    Returns:
        The staged proposal id and the expression diagnostics for each rule.
    """
    from tools.agents.schemas import ChangeSet  # local import keeps this module import-light

    try:
        change_set = ChangeSet.model_validate_json(change_set_json)
    except Exception as exc:  # noqa: BLE001 -- surfaced to the agent as a tool result
        return {"staged": False, "error": f"ChangeSet did not validate: {exc}"}

    with session_scope() as session:
        return stage_proposal(session, case_id, change_set, origin)


def stage_proposal(session: Any, case_id: str, change_set: Any, origin: str) -> dict[str, Any]:
    """Write a validated ChangeSet to the staging table using the caller's session.

    The server calls this after a drafter run so the proposal lands in the same
    transaction as its audit event. Never handed to an agent.
    """
    diagnostics: list[dict[str, Any]] = []
    for index, rule in enumerate(change_set.rules):
        if rule.other_logic:
            result = check_expression(rule.other_logic)
            if result["errors"] or result["warnings"]:
                diagnostics.append({
                    "rule_index": index,
                    "expression": rule.other_logic,
                    "errors": result["errors"],
                    "warnings": result["warnings"],
                })

    proposal = ProposedChange(
        case_id=case_id,
        origin=origin,
        payload=change_set.model_dump(mode="json"),
        rationale=change_set.summary,
        status="PROPOSED",
    )
    session.add(proposal)
    session.flush()
    proposal_id = proposal.id

    return {
        "staged": True,
        "proposal_id": proposal_id,
        "status": "PROPOSED",
        "rules_proposed": len(change_set.rules),
        "expression_diagnostics": diagnostics,
        "note": "Staged only. A human must accept this before any rule changes.",
    }


#: Read-only tools, safe for any agent.
READ_TOOLS = [
    list_requirement_groups,
    find_similar_rules,
    get_requirement_definition,
    check_expression,
    country_package_status,
    validate_rule_set,
    list_rule_sets,
]

#: Tools that write to the staging table only.
PROPOSE_TOOLS = [stage_change_set]
