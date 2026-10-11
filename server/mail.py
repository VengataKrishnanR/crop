"""Admin: email (SMTP) settings, test email, and the log of every email sent."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from tools.core.db import get_session
from tools.core.mailer import clean_addresses, get_settings, outbox_dir, send_email
from tools.core.models import AuditEvent, Notification
from tools.core.security import encrypt_secret

from .auth import CurrentUser, require_admin, require_internal

router = APIRouter()


class MailSettingsIn(BaseModel):
    host: Optional[str] = Field(default=None, description="SMTP host; empty = write emails to the outbox folder")
    port: int = 587
    security: str = "starttls"
    username: Optional[str] = None
    password: Optional[str] = Field(default=None, description="Write-only; omit to keep")
    clear_password: bool = False
    from_address: str = "ccre-onboarding@localhost"
    public_url: str = "http://localhost:8000"


class TestMail(BaseModel):
    to: str


def _settings_out(s) -> dict[str, Any]:
    return {"host": s.host, "port": s.port, "security": s.security, "username": s.username,
            "password_set": bool(s.password_enc), "from_address": s.from_address, "public_url": s.public_url,
            "mode": "smtp" if s.host else "outbox", "outbox_folder": str(outbox_dir())}


def notification_out(n: Notification) -> dict[str, Any]:
    return {"id": n.id, "case_id": n.case_id, "kind": n.kind, "state": n.state, "to": n.to, "cc": n.cc,
            "subject": n.subject, "body": n.body, "status": n.status, "error": n.error, "sent_by": n.sent_by,
            "at": n.at.isoformat() if n.at else None}


@router.get("/admin/mail", tags=["admin"])
def mail_settings(_: CurrentUser = Depends(require_admin),
                  session: Session = Depends(get_session)) -> dict[str, Any]:
    s = get_settings(session)
    session.commit()
    return _settings_out(s)


@router.put("/admin/mail", tags=["admin"])
def update_mail(body: MailSettingsIn, admin: CurrentUser = Depends(require_admin),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    if body.security not in {"starttls", "ssl", "none"}:
        raise HTTPException(400, "Security must be starttls, ssl or none.")
    try:
        clean_addresses([body.from_address])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    s = get_settings(session)
    s.host = (body.host or "").strip() or None
    s.port, s.security = body.port, body.security
    s.username = (body.username or "").strip() or None
    s.from_address, s.public_url = body.from_address.strip(), body.public_url.strip().rstrip("/")
    if body.clear_password:
        s.password_enc = None
    elif body.password:
        s.password_enc = encrypt_secret(body.password)
    s.updated_by = admin.label
    session.add(AuditEvent(actor=admin.email, action="admin:mail_settings", detail={"host": s.host}))
    session.commit()
    return _settings_out(s)


@router.post("/admin/mail/test", tags=["admin"])
def test_mail(body: TestMail, admin: CurrentUser = Depends(require_admin),
              session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        note = send_email(session, kind="TEST", subject="CCRE onboarding — test email",
                          body="This is a test email from the CCRE Rules Intelligence platform.",
                          to=[body.to], sent_by=admin.label)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    session.commit()
    return notification_out(note)


@router.get("/admin/notifications", tags=["admin"])
def notifications(limit: int = 50, _: CurrentUser = Depends(require_admin),
                  session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.execute(select(Notification).order_by(Notification.at.desc()).limit(min(limit, 500))).scalars()
    return [notification_out(n) for n in rows]


@router.get("/onboardings/{case_id}/notifications", tags=["lifecycle"])
def case_notifications(case_id: str, _: CurrentUser = Depends(require_internal),
                       session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = session.execute(select(Notification).where(Notification.case_id == case_id)
                           .order_by(Notification.at.desc())).scalars()
    return [notification_out(n) for n in rows]
