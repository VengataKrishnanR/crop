"""Milestones, the PM questionnaire, the baseline estimator and plan validation."""
from __future__ import annotations

import datetime as dt
import math
import re
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tools.core.models import CtryProcMapping, Rule, SirgDef

if TYPE_CHECKING:
    from tools.agents.harness.errors import GateResult

# The onboarding sequence, in order. ``stage`` keys are stable identifiers.
MILESTONES: tuple[dict[str, str], ...] = (
    {"stage": "RULE_CONFIG_DMG", "name": "Rule config + DMG changes", "owner": "CCRE team"},
    {"stage": "SANITY_CHECK", "name": "Sanity check", "owner": "CCRE team"},
    {"stage": "UAT_TC_PREP", "name": "UAT test case preparation", "owner": "CCRE team"},
    {"stage": "UAT_TC_REVIEW", "name": "UAT test case review", "owner": "CCRE team + Business"},
    {"stage": "UAT_EXECUTION", "name": "UAT execution", "owner": "CCRE team"},
    {"stage": "UAT_REVIEW_SIGNOFF", "name": "UAT review and sign-off", "owner": "CCRE team + Business"},
    {"stage": "RTP", "name": "RTP (ready to production)", "owner": "CCRE team + Support"},
)
STAGE_KEYS = [m["stage"] for m in MILESTONES]

# Structured questions asked of the PM before the plan is generated.
QUESTIONS: tuple[dict[str, Any], ...] = (
    {"id": "requested_rtp", "question": "What is the requested go-live (RTP) date?",
     "type": "date", "required": True},
    {"id": "earliest_start", "question": "When can the CCRE team start rule configuration?",
     "type": "date", "required": True},
    {"id": "ccre_capacity", "question": "How many CCRE team members are assigned to this onboarding?",
     "type": "number", "required": True, "default": 1},
    {"id": "dmg_change_required", "question": "Are DMG (message / attribute) changes needed?",
     "type": "choice", "options": ["yes", "no", "unknown"], "required": True, "default": "unknown"},
    {"id": "package_rebuild_days",
     "question": "Lead time for Support to rebuild and upload the config package (working days)?",
     "type": "number", "default": 5},
    {"id": "business_review_days",
     "question": "Working days the business team needs to review the UAT test cases?",
     "type": "number", "default": 3},
    {"id": "business_signoff_days",
     "question": "Working days the business team needs for UAT review and sign-off?",
     "type": "number", "default": 3},
    {"id": "uat_environment_ready", "question": "Is the UAT environment available for this country?",
     "type": "choice", "options": ["yes", "no", "unknown"], "default": "yes"},
    {"id": "blackout_dates",
     "question": "Holidays or freeze dates to avoid (YYYY-MM-DD, comma separated)?",
     "type": "text", "default": ""},
    {"id": "priority", "question": "Business priority?",
     "type": "choice", "options": ["low", "medium", "high", "critical"], "default": "medium"},
    {"id": "notes", "question": "Anything else the plan must respect (dependencies, other releases)?",
     "type": "text", "default": ""},
)

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


# --------------------------------------------------------------------------- #
# answers
# --------------------------------------------------------------------------- #

def normalise_answers(raw: dict[str, Any]) -> dict[str, Any]:
    """Apply defaults, coerce types, and raise ValueError naming every missing answer."""
    out: dict[str, Any] = {}
    missing: list[str] = []
    for q in QUESTIONS:
        value = raw.get(q["id"])
        if value in (None, ""):
            value = q.get("default")
        if value in (None, "") and q.get("required"):
            missing.append(q["question"])
            continue
        if q["type"] == "date" and value not in (None, ""):
            try:
                value = dt.date.fromisoformat(str(value)).isoformat()
            except ValueError as exc:
                raise ValueError(f"'{q['question']}' needs a date as YYYY-MM-DD.") from exc
        elif q["type"] == "number" and value not in (None, ""):
            try:
                value = max(0, int(float(value)))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"'{q['question']}' needs a number.") from exc
        elif q["type"] == "choice" and value not in q["options"]:
            raise ValueError(f"'{q['question']}' must be one of {', '.join(q['options'])}.")
        out[q["id"]] = value
    if missing:
        raise ValueError("Please answer: " + "; ".join(missing))
    if out["ccre_capacity"] < 1:
        raise ValueError("At least one CCRE team member must be assigned.")
    if dt.date.fromisoformat(out["requested_rtp"]) < dt.date.fromisoformat(out["earliest_start"]):
        raise ValueError("The requested RTP date is before the earliest start date.")
    return out


def _blackouts(answers: dict[str, Any]) -> set[dt.date]:
    dates: set[dt.date] = set()
    for token in _DATE.findall(str(answers.get("blackout_dates") or "")):
        try:
            dates.add(dt.date.fromisoformat(token))
        except ValueError:
            continue
    return dates


# --------------------------------------------------------------------------- #
# working days
# --------------------------------------------------------------------------- #

def _is_working(day: dt.date, blackout: set[dt.date]) -> bool:
    return day.weekday() < 5 and day not in blackout


def next_working_day(day: dt.date, blackout: set[dt.date]) -> dt.date:
    while not _is_working(day, blackout):
        day += dt.timedelta(days=1)
    return day


def add_working_days(start: dt.date, days: int, blackout: Optional[set[dt.date]] = None) -> dt.date:
    """End date of a ``days``-long task starting on ``start`` (inclusive)."""
    blackout = blackout or set()
    day = next_working_day(start, blackout)
    remaining = max(1, days) - 1
    while remaining > 0:
        day += dt.timedelta(days=1)
        if _is_working(day, blackout):
            remaining -= 1
    return day


def working_days_between(start: dt.date, end: dt.date) -> int:
    if end < start:
        return -working_days_between(end, start)
    days, day = 0, start
    while day < end:
        day += dt.timedelta(days=1)
        if day.weekday() < 5:
            days += 1
    return days


# --------------------------------------------------------------------------- #
# complexity facts and the baseline estimate
# --------------------------------------------------------------------------- #

def complexity_facts(session: Session, country: str, structured: dict[str, Any],
                     rule_set_id: Optional[str] = None) -> dict[str, Any]:
    """What drives effort: groups, conditions, rules already drafted, package gaps."""
    country = (country or "").upper()
    groups = [g.upper() for g in (structured.get("requirement_groups") or [])]
    mapped = set(session.execute(
        select(SirgDef.cd).join(CtryProcMapping, CtryProcMapping.sirg_id == SirgDef.id)
        .where(CtryProcMapping.ctry_cd == country).distinct()
    ).scalars())
    rules = 0
    if rule_set_id:
        rules = session.execute(
            select(func.count()).select_from(Rule).where(Rule.rule_set_id == rule_set_id)
        ).scalar_one()
    return {
        "country": country,
        "requirement_groups": groups,
        "group_count": len(groups),
        "condition_count": len(structured.get("conditions") or []),
        "rules_in_draft": rules,
        "country_in_package": bool(mapped),
        "groups_missing_from_package": sorted(g for g in groups if g not in mapped),
    }


def estimate(facts: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    """Deterministic baseline plan in working days. The AI planner starts from this."""
    blackout = _blackouts(answers)
    capacity = max(1, int(answers.get("ccre_capacity") or 1))
    groups = max(1, int(facts.get("group_count") or 1))
    conditions = int(facts.get("condition_count") or 0)
    dmg = {"yes": 3, "unknown": 1}.get(answers.get("dmg_change_required"), 0)
    package_gap = (not facts.get("country_in_package")) or bool(facts.get("groups_missing_from_package"))

    config_effort = 3 + groups + math.ceil(conditions / 2) + dmg
    durations = {
        "RULE_CONFIG_DMG": math.ceil(config_effort / capacity)
        + (int(answers.get("package_rebuild_days") or 0) if package_gap else 0),
        "SANITY_CHECK": 2,
        "UAT_TC_PREP": max(2, math.ceil((2 + 2 * groups) / capacity)),
        "UAT_TC_REVIEW": 1 + int(answers.get("business_review_days") or 3),
        "UAT_EXECUTION": 2 + groups + (3 if answers.get("uat_environment_ready") != "yes" else 0),
        "UAT_REVIEW_SIGNOFF": 1 + int(answers.get("business_signoff_days") or 3),
        "RTP": 2,
    }
    milestones = []
    cursor = next_working_day(dt.date.fromisoformat(answers["earliest_start"]), blackout)
    for m in MILESTONES:
        end = add_working_days(cursor, durations[m["stage"]], blackout)
        milestones.append({**m, "start": cursor.isoformat(), "end": end.isoformat(),
                           "working_days": durations[m["stage"]]})
        cursor = next_working_day(end + dt.timedelta(days=1), blackout)

    assumptions = [
        f"{capacity} CCRE team member(s); effort scaled by {groups} requirement group(s) "
        f"and {conditions} condition(s).",
        "Weekends and the listed blackout dates are non-working.",
    ]
    if package_gap:
        assumptions.append(
            f"A config package rebuild is needed ({answers.get('package_rebuild_days')} working days "
            "added to rule config)."
        )
    if dmg:
        assumptions.append("DMG changes are included in rule configuration.")
    return {"milestones": milestones, "assumptions": assumptions}


# --------------------------------------------------------------------------- #
# validation and risk
# --------------------------------------------------------------------------- #

def validate_plan(milestones: list[dict[str, Any]], answers: dict[str, Any]) -> dict[str, Any]:
    """Structural checks every plan must pass, plus the schedule risk.

    Raises ValueError on a structural defect (fed back to the planner for repair);
    returns ``{"at_risk": bool, "risks": [...]}`` otherwise.
    """
    stages = [m.get("stage") for m in milestones]
    if stages != STAGE_KEYS:
        raise ValueError(f"Milestones must be exactly, in order: {', '.join(STAGE_KEYS)}.")
    previous_start: Optional[dt.date] = None
    for m in milestones:
        try:
            start = dt.date.fromisoformat(str(m["start"]))
            end = dt.date.fromisoformat(str(m["end"]))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Milestone {m.get('stage')} needs start and end dates as YYYY-MM-DD.") from exc
        if end < start:
            raise ValueError(f"Milestone {m['stage']} ends before it starts.")
        if previous_start and start < previous_start:
            raise ValueError(f"Milestone {m['stage']} starts before the previous milestone.")
        previous_start = start

    risks: list[str] = []
    rtp_end = dt.date.fromisoformat(str(milestones[-1]["end"]))
    requested = dt.date.fromisoformat(answers["requested_rtp"])
    start = dt.date.fromisoformat(str(milestones[0]["start"]))
    earliest = dt.date.fromisoformat(answers["earliest_start"])
    if start < earliest:
        raise ValueError("The plan starts before the earliest start date the PM gave.")
    at_risk = rtp_end > requested
    if at_risk:
        slip = working_days_between(requested, rtp_end)
        risks.append(f"Planned RTP {rtp_end.isoformat()} is {slip} working day(s) after the "
                     f"requested date {requested.isoformat()}.")
    return {"at_risk": at_risk, "risks": risks}


def gate_plan(milestones: list[dict[str, Any]], answers: dict[str, Any]) -> "GateResult":
    """The plan gate as a :class:`GateResult` (docs/adr/0002).

    Reports every defect at once, with a path into the plan. Beyond
    :func:`validate_plan` it also refuses start/end dates on a weekend or a
    blackout date, as the design's plan gate requires. "At risk" is a warning:
    it is computed here, never trusted from the planner, and does not block.
    """
    from tools.agents.harness.errors import GateError, GateResult

    errors: list[GateError] = []
    stages = [m.get("stage") for m in milestones]
    if len(stages) != len(STAGE_KEYS):
        errors.append(GateError(code="PLAN_STAGES", path="milestones",
                                message=f"The plan has {len(stages)} milestone(s); exactly {len(STAGE_KEYS)} are required.",
                                hint=f"Use exactly, in order: {', '.join(STAGE_KEYS)}."))
    else:
        for i, (got, want) in enumerate(zip(stages, STAGE_KEYS)):
            if got != want:
                errors.append(GateError(code="PLAN_STAGES", path=f"milestones[{i}].stage",
                                        message=f"Milestone {i + 1} is {got!r}; expected {want!r}.",
                                        hint=f"Use exactly, in order: {', '.join(STAGE_KEYS)}."))

    blackout = _blackouts(answers)
    dates: list[Optional[tuple[dt.date, dt.date]]] = []
    for i, m in enumerate(milestones):
        parsed: dict[str, dt.date] = {}
        for key in ("start", "end"):
            try:
                parsed[key] = dt.date.fromisoformat(str(m[key]))
            except (KeyError, ValueError):
                errors.append(GateError(code="PLAN_DATE_FORMAT", path=f"milestones[{i}].{key}",
                                        message=f"Milestone {m.get('stage')} has no valid {key} date.",
                                        hint="Write dates as YYYY-MM-DD."))
        if len(parsed) < 2:
            dates.append(None)
            continue
        start, end = parsed["start"], parsed["end"]
        dates.append((start, end))
        if end < start:
            errors.append(GateError(code="PLAN_END_BEFORE_START", path=f"milestones[{i}].end",
                                    message=f"Milestone {m.get('stage')} ends ({end}) before it starts ({start}).",
                                    hint=f"Set the end on or after {start.isoformat()}."))
        for key, day in (("start", start), ("end", end)):
            if not _is_working(day, blackout):
                why = "a blackout date" if day in blackout else "a weekend"
                errors.append(GateError(code="PLAN_NON_WORKING_DAY", path=f"milestones[{i}].{key}",
                                        message=f"Milestone {m.get('stage')} {key} {day.isoformat()} is {why}.",
                                        hint=f"Use the next working day, {next_working_day(day, blackout).isoformat()}."))

    previous: Optional[dt.date] = None
    for i, pair in enumerate(dates):
        if pair is None:
            continue
        if previous and pair[0] < previous:
            errors.append(GateError(code="PLAN_ORDER", path=f"milestones[{i}].start",
                                    message=f"Milestone {milestones[i].get('stage')} starts before the previous one "
                                            f"({previous.isoformat()}).",
                                    hint=f"Start on or after {previous.isoformat()}."))
        previous = pair[0]

    if dates and dates[0] is not None and answers.get("earliest_start"):
        earliest = dt.date.fromisoformat(str(answers["earliest_start"]))
        if dates[0][0] < earliest:
            errors.append(GateError(code="PLAN_BEFORE_EARLIEST", path="milestones[0].start",
                                    message=f"The plan starts {dates[0][0].isoformat()}, before the earliest start "
                                            f"{earliest.isoformat()} the PM gave.",
                                    hint=f"Start on or after {earliest.isoformat()}."))
    if dates and dates[-1] is not None and answers.get("requested_rtp") and len(dates) == len(STAGE_KEYS):
        requested = dt.date.fromisoformat(str(answers["requested_rtp"]))
        rtp_end = dates[-1][1]
        if rtp_end > requested:
            errors.append(GateError(code="PLAN_AT_RISK", path=f"milestones[{len(dates) - 1}].end",
                                    severity="warning",
                                    message=f"Planned RTP {rtp_end.isoformat()} is "
                                            f"{working_days_between(requested, rtp_end)} working day(s) after the "
                                            f"requested date {requested.isoformat()}.",
                                    hint="Keep the realistic date and flag the plan at risk; do not compress stages."))
    return GateResult.from_errors(errors)
