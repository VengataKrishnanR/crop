"""
Central configuration for the logging component.

All logging parameters are read once by load_logging_settings() and
returned as an immutable LoggingSettings instance.

Public API
----------
  LoggingSettings       — frozen dataclass with all logging config fields
  load_logging_settings — factory that reads env vars and returns LoggingSettings

Env vars
--------
  LOG_LEVEL   — log verbosity: DEBUG | INFO (default) | WARNING | ERROR | CRITICAL

Note
----
  The default ``INFO`` matches the ADK CLI default (``adk web --log_level``).
  Use ``WARNING`` or higher in production to suppress verbose operational logs.
  Set ``LOG_LEVEL=DEBUG`` only when actively troubleshooting; DEBUG logs can
  be very verbose and may expose sensitive prompt content.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

_DEFAULT_LEVEL = "INFO"


@dataclass(frozen=True)
class LoggingSettings:
    """Immutable snapshot of logging configuration."""

    level: int
    """Resolved :mod:`logging` level integer (e.g. ``logging.DEBUG``)."""

    level_name: str
    """Canonical level name as returned by ``logging.getLevelName(level)``."""


def load_logging_settings() -> LoggingSettings:
    """Return a LoggingSettings populated from the ``LOG_LEVEL`` env var.

    An unrecognised value falls back to ``WARNING`` and emits a warning.

    Returns:
        Frozen :class:`LoggingSettings` with the resolved level.
    """
    raw = os.getenv("LOG_LEVEL", _DEFAULT_LEVEL).upper()
    level = getattr(logging, raw, None)
    if not isinstance(level, int):
        logging.warning("Unknown LOG_LEVEL %r — falling back to WARNING.", raw)
        level = logging.WARNING
        raw = "WARNING"
    return LoggingSettings(level=level, level_name=raw)
