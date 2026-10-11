"""Domain configuration for the CCRE rule layer.

Everything is environment-driven so DEV / TEST / UAT differ only by env, never by
code. LLM settings live in ``components/llm/settings.py`` and HTTP-server settings
in ``server/config.py``; this module covers only the database and the reference
artifacts.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
# The reference artifacts (M2C workbook, sir-configuration package) sit beside
# the application folder, not inside it.
WORKSPACE_ROOT = REPO_ROOT.parent

# Same precedence as components/llm/settings.py: the project-root .env wins.
for _candidate in (REPO_ROOT / ".env", REPO_ROOT / "config" / ".env"):
    if _candidate.exists():
        load_dotenv(_candidate, override=False)


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _default_database_url() -> str:
    data_dir = Path(_env("CCRE_DATA_DIR", str(REPO_ROOT / ".ccre_data")))
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(data_dir / 'ccre.db').as_posix()}"


@dataclass(frozen=True)
class Settings:
    # SQLite by default so the platform runs with no infrastructure; the model is
    # Postgres-compatible and CCRE_DATABASE_URL swaps it with no code change.
    database_url: str = field(default_factory=lambda: _env("CCRE_DATABASE_URL", _default_database_url()))
    reference_dir: Path = field(default_factory=lambda: Path(_env("CCRE_REFERENCE_DIR", str(WORKSPACE_ROOT / "Reference"))))
    # The advisory layer is optional. Switched off, the platform still ingests,
    # validates, gates and exports -- it simply offers no drafts.
    agents_enabled: bool = field(default_factory=lambda: _env("CCRE_AGENTS_ENABLED", "1") not in {"0", "false", "False"})
    echo_sql: bool = field(default_factory=lambda: _env("CCRE_ECHO_SQL", "0") == "1")


SETTINGS = Settings()

# Processing level is IMP_CLR for every row observed in the config package;
# export clearance is not configured upstream yet.
DEFAULT_PROC_LVL = "IMP_CLR"
