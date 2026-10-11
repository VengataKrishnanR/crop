"""FastAPI application — HTTP shell over the CCRE rule layer and its agents.

Surface (all under ``/api``):
  - Domain routes (:mod:`server.routes`): ingestion, catalogue, cases & workflow,
    rules, deterministic validation, proposals, export.
  - Advisory routes (this module): run the four specialist agents, each output
    validated against its schema and recorded on the audit trail.
  - UI facade: ``/api/session`` + ``/api/run`` (chat with the root orchestrator),
    ``/api/test-report/xlsx``, and the single-page UI from ``ui/``.

Notice what is absent: there is no endpoint that writes to CCRE, and no endpoint
that advances a case past a gate without the validator agreeing.
"""
from __future__ import annotations

import re as _re
import uuid
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# ADK monkey-patch: allow literal curly braces in agent instruction files.
# ADK's inject_session_state raises KeyError for a {name} it cannot resolve as
# a session variable. Override it to pass those through untouched so prompts
# can show JSON shapes and expression examples verbatim.
# ---------------------------------------------------------------------------
try:
    import google.adk.utils.instructions_utils as _iu

    async def _safe_inject_session_state(template, context):
        result = []
        last = 0
        for m in _re.finditer(r"{+[^{}]*}+", template):
            result.append(template[last:m.start()])
            full = m.group(0)
            var_name = full.strip("{}").strip()
            try:
                val = context.state[var_name] if hasattr(context, "state") else context[var_name]
                result.append(str(val) if val is not None else full)
            except Exception:
                result.append(full)  # not a session var — leave as-is
            last = m.end()
        result.append(template[last:])
        return "".join(result)

    _iu.inject_session_state = _safe_inject_session_state
except ImportError:
    pass  # ADK not installed yet — the domain API still works without it

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from tools.agents import AGENT_SPECS, agents_available
from tools.core.db import get_session, init_db
from tools.core.models import OnboardingCase, RuleSet

from . import api_schemas as S
from .advisory import AdvisoryService, AdvisoryUnavailable
from .agent_invoker import AgentInvocationError
from .config import load_settings
from .routes import router as domain_router

settings = load_settings()
advisory = AdvisoryService()

app = FastAPI(
    title="CCRE Rules Intelligence & Onboarding Platform",
    version="1.0.0",
    description=(
        "Rule authoring, deterministic validation, gated approval and export for CCRE country "
        "onboarding, with an ADK advisory layer that recommends and never decides. The "
        "platform holds no credential for CCRE: releases leave as an export that Support uploads."
    ),
)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ---------------------------------------------------------------------------
# Authentication — optional shared-secret gate on the API surface.
#   AUTH_MODE=none   (default) — open, for local dev.
#   AUTH_MODE=apikey           — every /api/* call (except /api/health) must
#                                present CCRE_API_KEY via `Authorization: Bearer <k>`
#                                or `X-API-Key: <k>`. Static UI assets stay open.
# ---------------------------------------------------------------------------
_OPEN_PATHS = {"/api/health"}


@app.middleware("http")
async def _auth_guard(request, call_next):
    if settings.auth_mode == "apikey":
        path = request.url.path
        if path.startswith("/api/") and path not in _OPEN_PATHS:
            presented = request.headers.get("x-api-key", "")
            authz = request.headers.get("authorization", "")
            if authz.lower().startswith("bearer "):
                presented = presented or authz[7:].strip()
            if not settings.api_key or presented != settings.api_key:
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)


app.include_router(domain_router, prefix="/api")


# ---------------------------------------------------------------------------
# Advisory (agent) endpoints
# ---------------------------------------------------------------------------

def _advise(fn, *args, **kwargs) -> dict[str, Any]:
    """Run an advisory call, mapping failures to clean HTTP errors."""
    try:
        return fn(*args, **kwargs)
    except AdvisoryUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except AgentInvocationError as exc:
        raise HTTPException(502, f"Agent failed: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _case(session: Session, case_id: str) -> OnboardingCase:
    case = session.get(OnboardingCase, case_id)
    if case is None:
        raise HTTPException(404, f"no such case: {case_id}")
    return case


@app.get("/api/agents", tags=["advisory"])
def list_agents() -> dict[str, Any]:
    """The advisory layer: what each agent does, what it emits, and which human gate follows."""
    available, reason = agents_available()
    return {"llm_mode": settings.llm_mode, "available": available, "reason": reason,
            "agents": AGENT_SPECS}


@app.post("/api/cases/{case_id}/interpret", tags=["advisory"])
def interpret_requirement(case_id: str, body: S.InterpretRequest,
                          session: Session = Depends(get_session)) -> dict[str, Any]:
    """Requirement interpreter → RequirementInterpretation (recorded on the audit trail)."""
    case = _case(session, case_id)
    return _advise(advisory.interpret, session, case, body.requirement_text, body.actor)


@app.post("/api/cases/{case_id}/draft-rules", tags=["advisory"])
def draft_rules(case_id: str, body: S.DraftRulesRequest,
                session: Session = Depends(get_session)) -> dict[str, Any]:
    """Rule drafter → ChangeSet, staged as a PROPOSED proposal. Nothing is applied."""
    case = _case(session, case_id)
    return _advise(advisory.draft_rules, session, case, body.requirement_text,
                   body.interpretation, body.actor)


@app.post("/api/rule-sets/{rule_set_id}/test-suite", tags=["advisory"])
def design_test_suite(rule_set_id: str, body: S.DesignTestsRequest,
                      session: Session = Depends(get_session)) -> dict[str, Any]:
    """Test case designer → TestCaseSuite for the rules in scope."""
    rule_set = session.get(RuleSet, rule_set_id)
    if rule_set is None:
        raise HTTPException(404, f"no such rule set: {rule_set_id}")
    return _advise(advisory.design_tests, session, rule_set, body.country, body.notes, body.actor)


@app.post("/api/failures/analyse", tags=["advisory"])
def analyse_failure(body: S.AnalyseFailureRequest,
                    session: Session = Depends(get_session)) -> dict[str, Any]:
    """Failure analyst → FailureAnalysis. Recommends the next check; never edits."""
    if body.case_id:
        _case(session, body.case_id)
    return _advise(advisory.analyse_failure, session, body.test_id, body.expected, body.actual,
                   body.details, body.case_id, body.actor)


# ===========================================================================
# UI facade — conversational endpoints for the single-page UI (ui/)
# ===========================================================================
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_UI_DIR = _PROJECT_ROOT / "ui"


@app.post("/api/session", tags=["ui"])
def ui_session() -> dict[str, str]:
    """The UI tracks a session id; for the stateless facade any id works."""
    return {"session_id": uuid.uuid4().hex}


@app.post("/api/run", tags=["ui"])
def ui_run(body: S.ChatRequest) -> JSONResponse:
    """Send one message to the root orchestrator and return its reply."""
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "Empty message")
    try:
        response = advisory.chat(message)
    except AdvisoryUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:  # surface a clean error to the UI
        raise HTTPException(500, str(exc)) from exc
    return JSONResponse({"session_id": body.session_id or uuid.uuid4().hex, "response": response})


@app.api_route("/api/test-report/xlsx", methods=["GET", "HEAD"], tags=["ui"])
def download_test_report() -> FileResponse:
    """Download the latest XLSX test report generated by ``pytest``."""
    if not settings.test_report_path.exists():
        raise HTTPException(
            404,
            "Test report not found. Generate it by running:  pytest  "
            "The root conftest.py writes test_report.xlsx automatically.",
        )
    return FileResponse(
        settings.test_report_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="ccre_test_report.xlsx",
    )


@app.get("/", include_in_schema=False)
def ui_index() -> FileResponse:
    return FileResponse(_UI_DIR / "index.html")


# Serve the UI's static assets explicitly. A catch-all StaticFiles mount at "/"
# shadows the /api routes in Starlette, so we expose only the known files.
_UI_ASSETS = {
    "app.js": "application/javascript",
    "styles.css": "text/css",
    "ccre.css": "text/css",
}


@app.get("/{asset}", include_in_schema=False)
def ui_asset(asset: str) -> FileResponse:
    media = _UI_ASSETS.get(asset)
    path = _UI_DIR / asset
    if media is None or not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type=media)
