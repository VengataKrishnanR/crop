"""Sign-in and the admin panel's user management (RBAC)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tools.core.db import get_session
from tools.core.models import AuditEvent, User
from tools.core.security import (
    UserRole,
    authenticate,
    create_user,
    hash_password,
    issue_token,
    normalise_countries,
    validate_password_strength,
    verify_password,
)

from . import api_schemas as S
from .auth import CurrentUser, current_user, require_admin

router = APIRouter()

ROLE_DESCRIPTIONS = {
    "ADMIN": "Manages users and roles; full read access.",
    "PM": "Owns the timeline: answers the questionnaire, plans the dates (AI) and approves them.",
    "CCRE_CONSULTANT": "Reviews whether the requirement can be configured in CCRE and approves it; reviews test cases and UAT results.",
    "CCRE_TEAM": "Configures the M2C rules and DMG changes, prepares and runs UAT.",
    "BUSINESS": "Country business team: submits requirements, sees the timeline, reviews test cases and signs off UAT. Limited to assigned countries.",
}


def _user_out(user: User) -> dict[str, Any]:
    return {
        "id": user.id, "email": user.email, "name": user.name, "role": user.role,
        "active": user.active, "countries": list(user.countries or []),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


# --------------------------------------------------------------------------- #
# auth
# --------------------------------------------------------------------------- #

@router.post("/auth/login", tags=["auth"])
def login(body: S.LoginRequest, session: Session = Depends(get_session)) -> dict[str, Any]:
    user = authenticate(session, body.email, body.password)
    if user is None:
        raise HTTPException(401, "Email or password is incorrect, or the account is disabled.")
    session.add(AuditEvent(actor=user.email, action="auth:login", detail={"role": user.role}))
    session.commit()
    return {"token": issue_token(user), "user": _user_out(user)}


@router.get("/auth/me", tags=["auth"])
def me(user: CurrentUser = Depends(current_user)) -> dict[str, Any]:
    from .config import load_settings

    return {
        "id": user.id, "email": user.email, "name": user.name, "role": str(user.role),
        "countries": user.countries, "dev": user.dev, "is_business": user.is_business,
        "auth_mode": load_settings().auth_mode if not user.dev else "none",
    }


@router.post("/auth/change-password", tags=["auth"])
def change_password(body: S.ChangePasswordRequest, user: CurrentUser = Depends(current_user),
                    session: Session = Depends(get_session)) -> dict[str, str]:
    record = session.get(User, user.id)
    if record is None:
        raise HTTPException(400, "Development users have no password.")
    if not verify_password(body.current_password, record.password_hash):
        raise HTTPException(400, "The current password is incorrect.")
    try:
        validate_password_strength(body.new_password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    record.password_hash = hash_password(body.new_password)
    session.add(AuditEvent(actor=user.email, action="auth:password_changed", detail={}))
    session.commit()
    return {"status": "changed"}


# --------------------------------------------------------------------------- #
# admin panel
# --------------------------------------------------------------------------- #

@router.get("/admin/roles", tags=["admin"])
def roles(_: CurrentUser = Depends(require_admin)) -> dict[str, str]:
    return ROLE_DESCRIPTIONS


@router.get("/admin/users", tags=["admin"])
def list_users(_: CurrentUser = Depends(require_admin),
               session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    users = session.execute(select(User).order_by(User.role, User.name)).scalars()
    return [_user_out(u) for u in users]


@router.post("/admin/users", status_code=201, tags=["admin"])
def add_user(body: S.UserCreate, admin: CurrentUser = Depends(require_admin),
             session: Session = Depends(get_session)) -> dict[str, Any]:
    try:
        user = create_user(session, email=body.email, name=body.name, role=body.role,
                           password=body.password, countries=body.countries)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if user.role == UserRole.BUSINESS and not user.countries:
        session.rollback()
        raise HTTPException(400, "A business user must be assigned at least one country.")
    session.add(AuditEvent(actor=admin.email, action="admin:user_created",
                           detail={"user": user.email, "role": user.role, "countries": user.countries}))
    session.commit()
    return _user_out(user)


def _active_admins(session: Session) -> int:
    return session.execute(
        select(func.count()).select_from(User).where(User.role == UserRole.ADMIN, User.active.is_(True))
    ).scalar_one()


@router.patch("/admin/users/{user_id}", tags=["admin"])
def update_user(user_id: str, body: S.UserUpdate, admin: CurrentUser = Depends(require_admin),
                session: Session = Depends(get_session)) -> dict[str, Any]:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "No such user.")
    changes: dict[str, Any] = {}
    if body.role is not None:
        try:
            role = str(UserRole(body.role.upper()))
        except ValueError as exc:
            raise HTTPException(400, f"Unknown role: {body.role}") from exc
        if user.role == UserRole.ADMIN and role != UserRole.ADMIN and _active_admins(session) <= 1:
            raise HTTPException(409, "This is the last active admin; add another admin first.")
        changes["role"] = {"from": user.role, "to": role}
        user.role = role
    if body.active is not None and body.active != user.active:
        if not body.active and user.role == UserRole.ADMIN and _active_admins(session) <= 1:
            raise HTTPException(409, "This is the last active admin; it cannot be disabled.")
        changes["active"] = {"from": user.active, "to": body.active}
        user.active = body.active
    if body.name is not None:
        changes["name"] = {"from": user.name, "to": body.name}
        user.name = body.name.strip()
    if body.countries is not None:
        countries = normalise_countries(body.countries)
        changes["countries"] = {"from": list(user.countries or []), "to": countries}
        user.countries = countries
    if user.role == UserRole.BUSINESS and not user.countries:
        session.rollback()
        raise HTTPException(400, "A business user must be assigned at least one country.")
    session.add(AuditEvent(actor=admin.email, action="admin:user_updated",
                           detail={"user": user.email, "changes": changes}))
    session.commit()
    return _user_out(user)


@router.post("/admin/users/{user_id}/reset-password", tags=["admin"])
def reset_password(user_id: str, body: S.PasswordReset, admin: CurrentUser = Depends(require_admin),
                   session: Session = Depends(get_session)) -> dict[str, str]:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "No such user.")
    try:
        validate_password_strength(body.new_password)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    user.password_hash = hash_password(body.new_password)
    session.add(AuditEvent(actor=admin.email, action="admin:password_reset", detail={"user": user.email}))
    session.commit()
    return {"status": "reset"}
