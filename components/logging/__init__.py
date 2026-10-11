"""Logging component — public API.

Quickstart::

    from components.logging import configure_logging
    configure_logging()   # reads LOG_LEVEL env var (default: WARNING)
"""
from .config import configure_logging
from .settings import LoggingSettings, load_logging_settings

__all__ = [
    "configure_logging",
    "LoggingSettings",
    "load_logging_settings",
]
