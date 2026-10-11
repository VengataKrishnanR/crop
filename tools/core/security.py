"""Users, roles, password hashing and signed session tokens.

Standard library only: PBKDF2-SHA256 for passwords, HMAC-SHA256 for tokens. The
signing secret comes from ``CCRE_SECRET_KEY`` or, failing that, a random key
persisted once in the data directory so tokens survive a restart.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import time
from enum import StrEnum
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import REPO_ROOT
from .models import User


class UserRole(StrEnum):
    ADMIN = "ADMIN"                       # manages users; full read access
    PM = "PM"                             # approves the timeline
    CCRE_CONSULTANT = "CCRE_CONSULTANT"   # approves the requirement; reviews results
    CCRE_TEAM = "CCRE_TEAM"               # configures M2C/DMG, prepares and runs UAT
    BUSINESS = "BUSINESS"                 # country business team — limited business view


INTERNAL_ROLES = frozenset({UserRole.ADMIN, UserRole.PM, UserRole.CCRE_CONSULTANT, UserRole.CCRE_TEAM})
CCRE_ROLES = frozenset({UserRole.ADMIN, UserRole.CCRE_CONSULTANT, UserRole.CCRE_TEAM})
ALL_ROLES = frozenset(UserRole)

TOKEN_TTL_SECONDS = int(os.getenv("CCRE_TOKEN_TTL_SECONDS", str(12 * 3600)))
_PBKDF2_ROUNDS = 240_000


# --------------------------------------------------------------------------- #
# passwords
# --------------------------------------------------------------------------- #

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${_PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def validate_password_strength(password: str) -> None:
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")


# --------------------------------------------------------------------------- #
# tokens
# --------------------------------------------------------------------------- #

def _secret() -> bytes:
    env = os.getenv("CCRE_SECRET_KEY")
    if env:
        return env.encode("utf-8")
    data_dir = Path(os.getenv("CCRE_DATA_DIR", str(REPO_ROOT / ".ccre_data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    key_file = data_dir / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_hex(32), encoding="utf-8")
    return key_file.read_text(encoding="utf-8").strip().encode("utf-8")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(user: User) -> str:
    payload = {"sub": user.id, "role": user.role, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str) -> Optional[dict[str, Any]]:
    """Return the token payload, or None if it is malformed, forged or expired."""
    try:
        body, sig = token.split(".")
    except ValueError:
        return None
    expected = _b64(hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if int(payload.get("exp", 0)) < time.time():
        return None
    return payload


# --------------------------------------------------------------------------- #
# user management
# --------------------------------------------------------------------------- #

def normalise_countries(countries: Optional[list[str]]) -> list[str]:
    return sorted({c.strip().upper() for c in (countries or []) if c and c.strip()})


def create_user(session: Session, *, email: str, name: str, role: str, password: str,
                countries: Optional[list[str]] = None) -> User:
    email = email.strip().lower()
    role = UserRole(role.upper())
    validate_password_strength(password)
    if session.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise ValueError(f"A user with email {email} already exists.")
    user = User(email=email, name=name.strip(), role=str(role), password_hash=hash_password(password),
                countries=normalise_countries(countries), active=True)
    session.add(user)
    session.flush()
    return user


def authenticate(session: Session, email: str, password: str) -> Optional[User]:
    user = session.execute(
        select(User).where(User.email == email.strip().lower())
    ).scalar_one_or_none()
    if user is None or not user.active or not verify_password(password, user.password_hash):
        return None
    user.last_login_at = dt.datetime.now(dt.timezone.utc)
    return user


def ensure_default_admin(session: Session) -> Optional[str]:
    """Create the first ADMIN when no user exists. Returns its email if created."""
    if session.execute(select(func.count()).select_from(User)).scalar_one():
        return None
    email = os.getenv("CCRE_ADMIN_EMAIL", "admin@ccre.local")
    password = os.getenv("CCRE_ADMIN_PASSWORD", "ChangeMe123!")
    create_user(session, email=email, name="Administrator", role=UserRole.ADMIN, password=password)
    return email


def can_see_country(user: User, country: str) -> bool:
    """Internal roles see every country; a business user only their assigned ones."""
    if user.role != UserRole.BUSINESS:
        return True
    return country.upper() in set(user.countries or [])
