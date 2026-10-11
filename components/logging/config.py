"""Logging configuration for the CCRE onboarding ADK agent.

Apply once at startup via :func:`configure_logging`.

Usage
-----
::

    from components.logging import configure_logging
    configure_logging()          # reads LOG_LEVEL from env (default: INFO)

Or supply pre-built settings::

    from components.logging import configure_logging, load_logging_settings
    settings = load_logging_settings()
    configure_logging(settings)

Integration with ``adk web``
-----------------------------
``adk web --log_level DEBUG`` configures the root logger before agent modules
are imported.  When ``LOG_LEVEL`` is **not** set in the environment,
:func:`configure_logging` detects existing handlers and defers to whatever the
ADK CLI already configured.  Set ``LOG_LEVEL`` explicitly to override the CLI
flag (e.g. ``LOG_LEVEL=WARNING`` in production).
"""
from __future__ import annotations

import logging
import os

from .settings import LoggingSettings, load_logging_settings

# Matches the sample format shown in ADK observability docs.
_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def configure_logging(settings: LoggingSettings | None = None) -> None:
    """Configure the root logger.

    When *settings* is ``None`` and ``LOG_LEVEL`` is not set in the environment
    and the root logger already has handlers (e.g. ``adk web --log_level`` was
    used), this function is a no-op so the ADK CLI configuration is preserved.

    Args:
        settings: Pre-built :class:`~.settings.LoggingSettings`.  When
            ``None`` (the default), :func:`~.settings.load_logging_settings`
            is called to read the ``LOG_LEVEL`` environment variable.
    """
    env_explicit = "LOG_LEVEL" in os.environ
    caller_explicit = settings is not None

    if not caller_explicit and not env_explicit and logging.root.handlers:
        # Root logger already configured (e.g. by adk web --log_level).
        # Defer so our default does not silently override the CLI flag.
        return

    if settings is None:
        settings = load_logging_settings()

    logging.basicConfig(
        level=settings.level,
        format=_FORMAT,
        datefmt=_DATE_FORMAT,
        force=True,
    )
    logging.getLogger(__name__).debug(
        "Logging configured at level %s.", settings.level_name
    )
