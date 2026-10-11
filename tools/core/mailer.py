"""Outgoing email — SMTP when configured, otherwise the outbox folder.

Every message is logged as a :class:`Notification`, so what was sent, to whom
and when is always on record. Without an SMTP host (local development, offline
demos) messages are written as ``.eml`` files to ``.ccre_data/outbox`` and logged
with status ``OUTBOX`` — nothing silently disappears.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from .config import REPO_ROOT
from .models import MailSettings, Notification
from .security import decrypt_secret

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_addresses(values: Iterable[str]) -> list[str]:
    """Split, trim, de-duplicate and validate addresses (raises ValueError on a bad one)."""
    out: list[str] = []
    for raw in values or []:
        for part in re.split(r"[,;\s]+", str(raw)):
            part = part.strip()
            if not part:
                continue
            if not _EMAIL.match(part):
                raise ValueError(f"Not a valid email address: {part}")
            if part.lower() not in {a.lower() for a in out}:
                out.append(part)
    return out


def get_settings(session: Session) -> MailSettings:
    settings = session.get(MailSettings, 1)
    if settings is None:
        settings = MailSettings(id=1)
        session.add(settings)
        session.flush()
    return settings


def outbox_dir() -> Path:
    path = Path(os.getenv("CCRE_DATA_DIR", str(REPO_ROOT / ".ccre_data"))) / "outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def send_email(session: Session, *, kind: str, subject: str, body: str, to: list[str],
               cc: Optional[list[str]] = None, case_id: Optional[str] = None, state: Optional[str] = None,
               sent_by: Optional[str] = None) -> Notification:
    """Send (or queue to the outbox) and log one message. Never raises on delivery failure."""
    settings = get_settings(session)
    to, cc = clean_addresses(to), [a for a in clean_addresses(cc or []) if a.lower() not in
                                   {t.lower() for t in clean_addresses(to)}]
    if not to:
        raise ValueError("There is nobody to send this email to.")

    msg = EmailMessage()
    msg["From"] = settings.from_address
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="ccre.local")
    msg.set_content(body)

    note = Notification(case_id=case_id, kind=kind, state=state, to=to, cc=cc, subject=subject, body=body,
                        status="OUTBOX", sent_by=sent_by)
    if not settings.host:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        (outbox_dir() / f"{stamp}_{kind.lower()}.eml").write_bytes(bytes(msg))
    else:
        try:
            password = decrypt_secret(settings.password_enc)
            if settings.security == "ssl":
                server = smtplib.SMTP_SSL(settings.host, settings.port, context=ssl.create_default_context(),
                                          timeout=20)
            else:
                server = smtplib.SMTP(settings.host, settings.port, timeout=20)
                if settings.security == "starttls":
                    server.starttls(context=ssl.create_default_context())
            with server:
                if settings.username and password:
                    server.login(settings.username, password)
                server.send_message(msg)
            note.status = "SENT"
        except (smtplib.SMTPException, OSError) as exc:
            note.status, note.error = "FAILED", f"{type(exc).__name__}: {exc}"
    session.add(note)
    session.flush()
    return note
