"""
Centralised configuration for the DHL GenAI Gateway (Apigee) connection.

All environment variable reads for Apigee are performed here. Other modules
(rest_llm, embeddings) call load_settings() instead of reading os.getenv directly.

URL resolution order (highest priority first):
  1. APIGEE_PROXY_URL_<ENVIRONMENT>  e.g. APIGEE_PROXY_URL_PRODUCTION or APIGEE_PROXY_URL_TESTING
  2. APIGEE_PROXY_URL                legacy / fallback (backward compatible)

This means switching APIGEE_ENVIRONMENT=testing automatically picks up
APIGEE_PROXY_URL_TESTING if set, with no other changes required.

Env vars
--------
  APIGEE_API_KEY                      – Bearer token (shared across environments)
  APIGEE_PROXY_URL_PRODUCTION         – Production proxy base URL (recommended)
  APIGEE_PROXY_URL_TESTING            – Testing/sandbox proxy base URL (recommended)
  APIGEE_PROXY_URL                    – Fallback URL when env-specific var is absent
  APIGEE_ENVIRONMENT                  – "production" (default) | "testing"
  APIGEE_DEFAULT_VERTEX_MODEL         – Default Vertex AI deployment ID
  APIGEE_DEFAULT_AZURE_OPENAI_MODEL   – Default Azure OpenAI deployment ID
  APIGEE_DEFAULT_EMBEDDING_MODEL      – Default embedding deployment ID
  AZURE_API_VERSION                   – Azure API version (default: 2024-10-21)
  APIGEE_STREAMING_ENABLED            – "true" | "false" (default: false)
  APIGEE_TIMEOUT_SECONDS              – HTTP timeout in seconds (default: 60.0)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_DEFAULT_API_VERSION = "2024-10-21"
_DEFAULT_TIMEOUT = 60.0

# Load .env — the active project-root .env wins (this is the file the documented
# `cp config/.env.<mode> .env` workflow produces). config/.env is loaded only as
# a fallback to fill any keys the root .env omits. override=False => root wins.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
for _candidate in (_PROJECT_ROOT / ".env", _PROJECT_ROOT / "config" / ".env"):
    if _candidate.exists():
        load_dotenv(_candidate, override=False)


@dataclass(frozen=True)
class ApigeeSettings:
    """Immutable snapshot of all Apigee configuration read from the environment.

    Obtain an instance via :func:`load_settings` rather than constructing directly.
    """

    proxy_url: str
    """Base URL for the Apigee proxy, resolved from the environment."""

    api_key: str
    """Bearer token used in ``Authorization: Bearer`` headers."""

    environment: str
    """Active environment name: ``"production"`` or ``"testing"``."""

    default_vertex_model: str
    """Default Vertex AI deployment ID (``APIGEE_DEFAULT_VERTEX_MODEL``)."""

    default_azure_model: str
    """Default Azure OpenAI deployment ID (``APIGEE_DEFAULT_AZURE_OPENAI_MODEL``)."""

    default_embedding_model: str
    """Default embedding deployment ID (``APIGEE_DEFAULT_EMBEDDING_MODEL``)."""

    azure_api_version: str
    """Azure REST API version string (``AZURE_API_VERSION``)."""

    streaming_enabled: bool
    """Whether streaming is enabled globally (``APIGEE_STREAMING_ENABLED``)."""

    timeout_seconds: float
    """HTTP request timeout in seconds (``APIGEE_TIMEOUT_SECONDS``)."""


def load_settings() -> ApigeeSettings:
    """Read all Apigee configuration from the environment and return a frozen settings object.

    The proxy URL is resolved as follows:
    - ``APIGEE_PROXY_URL_<ENV>`` (e.g. ``APIGEE_PROXY_URL_TESTING``) if set
    - otherwise ``APIGEE_PROXY_URL`` (legacy fallback)

    Returns:
        A frozen :class:`ApigeeSettings` instance.
    """
    environment = os.getenv("APIGEE_ENVIRONMENT", "production")
    proxy_url = (
        os.getenv(f"APIGEE_PROXY_URL_{environment.upper()}", "")
        or os.getenv("APIGEE_PROXY_URL", "")
    )
    return ApigeeSettings(
        proxy_url=proxy_url,
        api_key=os.getenv("APIGEE_API_KEY", ""),
        environment=environment,
        default_vertex_model=os.getenv("APIGEE_DEFAULT_VERTEX_MODEL", ""),
        default_azure_model=os.getenv("APIGEE_DEFAULT_AZURE_OPENAI_MODEL", ""),
        default_embedding_model=os.getenv("APIGEE_DEFAULT_EMBEDDING_MODEL", ""),
        azure_api_version=os.getenv("AZURE_API_VERSION", _DEFAULT_API_VERSION),
        streaming_enabled=os.getenv("APIGEE_STREAMING_ENABLED", "false").strip().lower() == "true",
        timeout_seconds=float(os.getenv("APIGEE_TIMEOUT_SECONDS", str(_DEFAULT_TIMEOUT))),
    )
