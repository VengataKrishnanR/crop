"""Server configuration, read once from the environment.

Mirrors the ``components/llm/settings.py`` pattern: all env reads happen here
behind a frozen dataclass obtained via :func:`load_settings`. Database and
reference-artifact settings live in ``tools/core/config.py``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class ServerSettings:
    """Immutable snapshot of server configuration."""

    auth_mode: str
    """``users`` (default — sign-in and RBAC) | ``none`` (local development only)."""

    llm_mode: str
    """Active ``CCRE_LLM_MODE`` (stub | openai | google-ai | apigee) — reported by /api/agents."""

    agent_timeout_seconds: float
    """Upper bound for one agent invocation."""

    test_report_path: Path
    """Where ``pytest`` writes the XLSX test report (root conftest.py)."""


def load_settings() -> ServerSettings:
    mode = os.getenv("AUTH_MODE", "users").strip().lower()
    if mode not in {"users", "none"}:
        mode = "users"
    return ServerSettings(
        auth_mode=mode,
        llm_mode=os.getenv("CCRE_LLM_MODE", "apigee").strip().lower(),
        agent_timeout_seconds=float(os.getenv("CCRE_AGENT_TIMEOUT_SECONDS", "120")),
        test_report_path=_PROJECT_ROOT / "test_report.xlsx",
    )
