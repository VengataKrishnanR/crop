"""Execution endpoints — configured by the admin, used by UAT runs.

The admin enters the URL, the credential header and value, and where the
response reports its result. The credential is encrypted at rest and never sent
back to the browser (only a masked hint). The CCRE team sees endpoint *names*
only, to pick where a UAT run goes.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from tools.core.db import get_session
from tools.core.models import AuditEvent, ExecutionEndpoint, PayloadTemplate
from tools.core.security import encrypt_secret, secret_hint
from tools.execution import check_response
from tools.execution.executor import EndpointExecutor

from . import api_schemas as S
from .auth import CurrentUser, require_admin, require_ccre

router = APIRouter()

PRESETS: dict[str, dict[str, Any]] = {
    "CRMS categorization rule engine": {
        "method": "POST", "auth_header": "x-api-key",
        "extra_headers": {"Content-Type": "application/json"},
        "groups_path": "MvmtMsg.Bd.Mvmt[].PcsInMvmt[].RqrReglDecTy[].TyCd",
        "case_flag_path": "",
        "status_path": "MvmtMsg.RespStatus[].Sev", "status_ok_value": "10",
        "compare_path": "MvmtMsg.Bd",
        "help": "From the CRMS API test suite: categorization result per piece; Sev 10 = success.",
    },
    "CCRE requirement evaluation": {
        "method": "POST", "auth_header": "x-api-key",
        "extra_headers": {"Content-Type": "application/json"},
        "groups_path": "requirements[].group", "case_flag_path": "caseCreated",
        "status_path": "", "status_ok_value": "", "compare_path": "",
        "help": "Default CCRE shape; adjust the paths to the real CCRE response.",
    },
}

_ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _out(e: ExecutionEndpoint) -> dict[str, Any]:
    return {
        "id": e.id, "name": e.name, "url": e.url, "method": e.method, "auth_header": e.auth_header,
        "secret_set": bool(e.secret_enc), "secret_hint": e.secret_hint,
        "extra_headers": e.extra_headers or {}, "timeout_seconds": e.timeout_seconds,
        "groups_path": e.groups_path, "case_flag_path": e.case_flag_path, "status_path": e.status_path,
        "status_ok_value": e.status_ok_value, "compare_path": e.compare_path, "active": e.active,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


def _validate(url: str | None, method: str | None, headers: dict | None) -> None:
    if url is not None and not url.lower().startswith(("https://", "http://")):
        raise HTTPException(400, "The endpoint URL must start with https:// or http://.")
    if method is not None and method.upper() not in _ALLOWED_METHODS:
        raise HTTPException(400, f"Method must be one of {', '.join(sorted(_ALLOWED_METHODS))}.")
    for key in (headers or {}):
        if key.lower() in {"x-api-key", "authorization"}:
            raise HTTPException(400, "Put the credential in the credential fields, not in extra headers, "
                                     "so it is stored encrypted.")


@router.get("/admin/endpoint-presets", tags=["admin"])
def presets(_: CurrentUser = Depends(require_admin)) -> dict[str, Any]:
    return PRESETS


@router.get("/admin/endpoints", tags=["admin"])
def list_endpoints(_: CurrentUser = Depends(require_admin),
                   session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_out(e) for e in session.execute(select(ExecutionEndpoint).order_by(ExecutionEndpoint.name)).scalars()]


@router.post("/admin/endpoints", status_code=201, tags=["admin"])
def create_endpoint(body: S.EndpointIn, admin: CurrentUser = Depends(require_admin),
                    session: Session = Depends(get_session)) -> dict[str, Any]:
    _validate(body.url, body.method, body.extra_headers)
    if session.execute(select(ExecutionEndpoint).where(ExecutionEndpoint.name == body.name.strip())
                       ).scalar_one_or_none():
        raise HTTPException(409, f"An endpoint named '{body.name}' already exists.")
    data = body.model_dump(exclude={"secret"})
    data["name"], data["method"] = body.name.strip(), body.method.upper()
    e = ExecutionEndpoint(**data, created_by=admin.label)
    if body.secret:
        e.secret_enc, e.secret_hint = encrypt_secret(body.secret), secret_hint(body.secret)
    session.add(e)
    session.add(AuditEvent(actor=admin.email, action="admin:endpoint_created",
                           detail={"name": e.name, "url": e.url, "credential": bool(body.secret)}))
    session.commit()
    return _out(e)


@router.patch("/admin/endpoints/{endpoint_id}", tags=["admin"])
def update_endpoint(endpoint_id: str, body: S.EndpointPatch, admin: CurrentUser = Depends(require_admin),
                    session: Session = Depends(get_session)) -> dict[str, Any]:
    e = session.get(ExecutionEndpoint, endpoint_id)
    if e is None:
        raise HTTPException(404, "No such endpoint.")
    _validate(body.url, body.method, body.extra_headers)
    changed = []
    for field, value in body.model_dump(exclude_unset=True, exclude={"secret", "clear_secret"}).items():
        if field == "method" and value:
            value = value.upper()
        setattr(e, field, value)
        changed.append(field)
    if body.clear_secret:
        e.secret_enc = e.secret_hint = None
        changed.append("credential cleared")
    elif body.secret:
        e.secret_enc, e.secret_hint = encrypt_secret(body.secret), secret_hint(body.secret)
        changed.append("credential replaced")
    session.add(AuditEvent(actor=admin.email, action="admin:endpoint_updated",
                           detail={"name": e.name, "changed": changed}))
    session.commit()
    return _out(e)


@router.delete("/admin/endpoints/{endpoint_id}", tags=["admin"])
def delete_endpoint(endpoint_id: str, admin: CurrentUser = Depends(require_admin),
                    session: Session = Depends(get_session)) -> dict[str, str]:
    e = session.get(ExecutionEndpoint, endpoint_id)
    if e is None:
        raise HTTPException(404, "No such endpoint.")
    session.delete(e)
    session.add(AuditEvent(actor=admin.email, action="admin:endpoint_deleted", detail={"name": e.name}))
    session.commit()
    return {"status": "deleted"}


@router.post("/admin/endpoints/{endpoint_id}/test", tags=["admin"])
def test_endpoint(endpoint_id: str, body: S.EndpointTest, admin: CurrentUser = Depends(require_admin),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    """Send one sample payload as-is and report reachability and whether the response is readable."""
    e = session.get(ExecutionEndpoint, endpoint_id)
    if e is None:
        raise HTTPException(404, "No such endpoint.")
    template = session.get(PayloadTemplate, body.template_id) if body.template_id else None
    payload = template.body if template is not None else {}
    try:
        outcome = EndpointExecutor.from_endpoint(e).execute(payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    check = check_response(outcome.body, outcome.status, None, False, groups_path=e.groups_path or None,
                           case_path=e.case_flag_path or "", status_path=e.status_path or None,
                           status_ok=e.status_ok_value)
    session.add(AuditEvent(actor=admin.email, action="admin:endpoint_tested",
                           detail={"name": e.name, "status": outcome.status, "error": outcome.error}))
    session.commit()
    return {
        "reachable": outcome.status is not None, "status": outcome.status,
        "latency_ms": round(outcome.latency_ms, 1), "error": outcome.error,
        "response_readable": bool(outcome.status and 200 <= outcome.status < 300 and check.get("conclusive")),
        "check": check.get("reasons", []),
        "sent": template.name if template is not None else "empty body",
    }


@router.get("/uat/endpoints", tags=["uat"])
def run_targets(_: CurrentUser = Depends(require_ccre),
                session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    """What the CCRE team may run against — names only, no URLs or credentials."""
    targets = session.execute(select(ExecutionEndpoint).where(ExecutionEndpoint.active.is_(True))
                              .order_by(ExecutionEndpoint.name)).scalars()
    return [{"id": e.id, "name": e.name, "comparable": bool(e.compare_path)} for e in targets]
