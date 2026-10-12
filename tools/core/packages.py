"""Which config package (beta file) the platform uses.

There is exactly one answer, used everywhere: the package an admin activated. Before
any upload has been activated (older installations), the most recently loaded package
is used, so nothing breaks — the Admin page shows that no package was activated yet.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ConfigPackage, PackageUpload


def active_upload(session: Session) -> Optional[PackageUpload]:
    return session.execute(select(PackageUpload).where(PackageUpload.status == "ACTIVE")
                           .order_by(PackageUpload.decided_at.desc()).limit(1)).scalar_one_or_none()


def active_package_version(session: Session) -> Optional[str]:
    up = active_upload(session)
    if up is not None:
        return up.version
    return session.execute(
        select(ConfigPackage.version).order_by(ConfigPackage.ingested_at.desc()).limit(1)
    ).scalar_one_or_none()
