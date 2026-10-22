"""Reference data access: one interface, chosen by ``REFERENCE_SOURCE`` (docs/adr/0003).

Every reader of workbook reference data -- intake pick-lists, rule configuration,
sanity checks, the validation snapshot, the M2C draft seed and the agent tools --
goes through :func:`get_reference`. Nothing outside this package and the legacy
ingestion itself reads the ingestion tables or the workbook parser.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from .base import MirrorSirgRow, MirrorSirRow, ReferenceBinding, ReferenceRepository, ReferenceRule
from .legacy import LegacyReferenceRepository
from .sirdb import SirdbReferenceRepository

__all__ = [
    "LegacyReferenceRepository", "MirrorSirRow", "MirrorSirgRow", "ReferenceBinding", "ReferenceRepository",
    "ReferenceRule", "SirdbReferenceRepository", "get_reference", "sirdb_engine",
]


@lru_cache(maxsize=4)
def sirdb_engine(url: Optional[str] = None) -> Engine:
    from tools.core.config import SETTINGS
    from tools.core.db import make_engine

    return make_engine(url or SETTINGS.sirdb_sqlalchemy_url)


def get_reference(session: Session, source: Optional[str] = None) -> ReferenceRepository:
    """The configured reference repository. ``source`` overrides the setting (tests, parity)."""
    from tools.core.config import SETTINGS

    chosen = source or SETTINGS.reference_source
    if chosen == "legacy":
        return LegacyReferenceRepository(session)
    if chosen == "sirdb":
        return SirdbReferenceRepository(sirdb_engine())
    raise ValueError(f"Unknown REFERENCE_SOURCE {chosen!r}.")
