"""FastAPI application — HTTP shell over the CCRE onboarding lifecycle and its agents.

Surface (all under ``/api``):
  - Auth + admin (:mod:`server.admin`): sign-in, users and roles (RBAC).
  - Lifecycle (:mod:`server.lifecycle`): one onboarding from intake to RTP —
    intake chat/form, timeline, M2C draft, sanity check, UAT prep/review/run/review.
  - KPIs (:mod:`server.kpis`).
  - Domain routes (:mod:`server.routes`, internal roles): ingestion, catalogue,
    rules, deterministic validation, proposals, export.
  - UI facade: ``/api/run`` (internal "Ask Expert" chat), ``/api/test-report/xlsx``,
    and the single-page UI from ``ui/``.

Notice what is absent: there is no endpoint that writes to CCRE, and no endpoint
that advances a case past a gate without the validator agreeing.
"""
from __future__ import annotations

import logging
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
from sqlalchemy import select
from sqlalchemy.orm import Session

from tools.agents import AGENT_SPECS, agents_available
from tools.core.config import SETTINGS
from tools.core.db import SessionLocal, get_session, init_db
from tools.core.models import ConfigPackage
from tools.core.security import ensure_default_admin
from tools.validation import available_checks

from . import api_schemas as S
from .admin import router as admin_router
from .advisory import AdvisoryService, AdvisoryUnavailable
from .auth import CurrentUser, current_user, require_internal
from .config import load_settings
from .collab import router as collab_router
from .downloads import router as download_router
from .endpoints import router as endpoint_router
from .kpis import router as kpi_router
from .lifecycle import ensure_builtin_template
from .lifecycle import router as lifecycle_router
from .mail import router as mail_router
from .ruleconfig_routes import router as ruleconfig_router
from .sanity_routes import router as sanity_router
from .routes import router as domain_router

log = logging.getLogger("ccre.server")
settings = load_settings()
advisory = AdvisoryService()

app = FastAPI(
    title="CCRE Rules Intelligence & Onboarding Platform",
    version="3.0.0",
    description=(
        "Country onboarding for CCRE from business requirement to RTP: intake (chat or form), "
        "AI timeline approved by the PM, M2C drafting with deterministic validation, UAT test "
        "design, payload generation, execution and review, with role-based access. Agents "
        "recommend; code validates; humans approve. The platform never uploads to CCRE."
    ),
)


@app.on_event("startup")
def _startup() -> None:
    init_db()
    with SessionLocal() as session:
        created = ensure_default_admin(session)
        session.commit()
        ensure_builtin_template(session)
    if created:
        log.warning("Created the first admin user %s — sign in and change its password "
                    "(set CCRE_ADMIN_EMAIL / CCRE_ADMIN_PASSWORD to choose them).", created)


@app.get("/api/health", tags=["meta"])
def health(session: Session = Depends(get_session)) -> dict[str, Any]:
    packages = list(session.execute(select(ConfigPackage)).scalars())
    return {
        "status": "ok",
        "version": app.version,
        "auth_mode": settings.auth_mode,
        "database": SETTINGS.database_url.split("://", 1)[0],
        "packages": [
            {"version": p.version, "sirg": p.sirg_count, "sir": p.sir_count, "mappings": p.mapping_count}
            for p in packages
        ],
        "checks": len(available_checks()),
    }


app.include_router(admin_router, prefix="/api")
app.include_router(lifecycle_router, prefix="/api")
app.include_router(kpi_router, prefix="/api")
app.include_router(endpoint_router, prefix="/api")
app.include_router(download_router, prefix="/api")
app.include_router(collab_router, prefix="/api")
app.include_router(mail_router, prefix="/api")
app.include_router(ruleconfig_router, prefix="/api")
app.include_router(sanity_router, prefix="/api")
app.include_router(domain_router, prefix="/api", dependencies=[Depends(require_internal)])


@app.get("/api/agents", tags=["advisory"])
def list_agents(_: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    """The advisory layer: what each agent does, what it emits, and which human gate follows."""
    available, reason = agents_available()
    return {"llm_mode": settings.llm_mode, "available": available, "reason": reason,
            "agents": AGENT_SPECS}


# ===========================================================================
# UI facade
# ===========================================================================
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_UI_DIR = _PROJECT_ROOT / "ui"


@app.post("/api/run", tags=["ui"])
def ui_run(body: S.ChatRequest, _: CurrentUser = Depends(require_internal)) -> JSONResponse:
    """Send one message to the internal "Ask Expert" orchestrator and return its reply."""
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


@app.head("/api/test-report/xlsx", include_in_schema=False)
def test_report_exists() -> FileResponse:
    return download_test_report()


@app.get("/api/test-report/xlsx", tags=["ui"])
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
