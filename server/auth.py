"""Authentication and role-based access control for the API.

``AUTH_MODE=users`` (default): every ``/api/*`` call except login and health needs
``Authorization: Bearer <token>`` from ``POST /api/auth/login``. The user's role
decides what they may call (:func:`require`) and which countries they see.

``AUTH_MODE=none`` (local development and tests only): every caller is a
development ADMIN, and the ``X-CCRE-Role`` header can act as another role so a
single person can walk the whole lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from tools.core.db import get_session
from tools.core.models import User
from tools.core.security import CCRE_ROLES, INTERNAL_ROLES, UserRole, read_token

from .config import load_settings


@dataclass
class CurrentUser:
    id: str
    email: str
    name: str
    role: UserRole
    # None means every country (internal roles, and anyone in AUTH_MODE=none)
    countries: Optional[list[str]] = field(default=None)
    dev: bool = False

    @property
    def is_business(self) -> bool:
        return self.role == UserRole.BUSINESS

    @property
    def is_internal(self) -> bool:
        return self.role in INTERNAL_ROLES

    def can_see(self, country: str) -> bool:
        if self.countries is None:
            return True
        return (country or "").upper() in set(self.countries)

    @property
    def label(self) -> str:
        return f"{self.name} <{self.email}>"


def _auth_mode() -> str:
    # Read per request so tests can switch modes with monkeypatch.
    import server.app as app_module

    return getattr(app_module, "settings", load_settings()).auth_mode


def current_user(request: Request, session: Session = Depends(get_session)) -> CurrentUser:
    if _auth_mode() == "none":
        raw_role = (request.headers.get("x-ccre-role") or "ADMIN").upper()
        try:
            role = UserRole(raw_role)
        except ValueError as exc:
            raise HTTPException(400, f"Unknown X-CCRE-Role: {raw_role}") from exc
        return CurrentUser(id="dev", email="dev@local", name=f"Developer ({role})", role=role,
                           countries=None, dev=True)

    authz = request.headers.get("authorization", "")
    token = authz[7:].strip() if authz.lower().startswith("bearer ") else ""
    payload = read_token(token) if token else None
    if payload is None:
        raise HTTPException(401, "Not signed in, or the session expired. Please sign in again.")
    user = session.get(User, payload["sub"])
    if user is None or not user.active:
        raise HTTPException(401, "This account is disabled.")
    role = UserRole(user.role)
    countries = list(user.countries or []) if role == UserRole.BUSINESS else None
    return CurrentUser(id=user.id, email=user.email, name=user.name, role=role, countries=countries)


def require(*roles: UserRole | str) -> Callable[..., CurrentUser]:
    """Dependency: the caller must hold one of ``roles``."""
    allowed = {UserRole(str(r)) for r in roles}

    def _dep(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if user.role not in allowed:
            names = ", ".join(sorted(str(r) for r in allowed))
            raise HTTPException(403, f"This action needs one of these roles: {names}.")
        return user

    return _dep


require_internal = require(*INTERNAL_ROLES)
require_ccre = require(*CCRE_ROLES)
require_admin = require(UserRole.ADMIN)
require_any = current_user


def ensure_country(user: CurrentUser, country: str) -> None:
    if not user.can_see(country):
        raise HTTPException(404, "No such onboarding.")  # do not reveal other countries


def roles_of(values: Iterable[str]) -> list[str]:
    return sorted(str(UserRole(v)) for v in values)
