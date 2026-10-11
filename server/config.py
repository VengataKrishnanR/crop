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
    """``none`` (dev) | ``apikey`` (shared-secret on every /api/* call except health)."""

    api_key: str
    """Shared secret required on /api/* when ``auth_mode == "apikey"``."""

    llm_mode: str
    """Active ``CCRE_LLM_MODE`` (stub | openai | google-ai | apigee) — reported by /api/agents."""

    agent_timeout_seconds: float
    """Upper bound for one agent invocation."""

    test_report_path: Path
    """Where ``pytest`` writes the XLSX test report (root conftest.py)."""


def load_settings() -> ServerSettings:
    return ServerSettings(
        auth_mode=os.getenv("AUTH_MODE", "none").strip().lower(),
        api_key=os.getenv("CCRE_API_KEY", ""),
        llm_mode=os.getenv("CCRE_LLM_MODE", "apigee").strip().lower(),
        agent_timeout_seconds=float(os.getenv("CCRE_AGENT_TIMEOUT_SECONDS", "120")),
        test_report_path=_PROJECT_ROOT / "test_report.xlsx",
    )
