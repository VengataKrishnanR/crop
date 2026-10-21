"""Domain configuration for the CCRE rule layer — typed, environment-driven settings.

DEV / TEST / UAT / PROD differ only by environment, never by code. LLM settings
live in ``components/llm/settings.py`` and HTTP-server settings in
``server/config.py``; this module covers the database, the reference data source
and the reference artifacts.

Database policy (docs/adr/0003):

* PostgreSQL is the default. ``CCRE_DATABASE_URL`` must point at it unless
  ``APP_ENV=dev-sqlite``.
* SQLite is allowed only with ``APP_ENV=dev-sqlite`` (offline quick start, fast
  tests) and is refused outright when ``APP_ENV=prod``.
* ``REFERENCE_SOURCE`` chooses where reference data is read: ``sirdb`` (default,
  the single source of truth) or ``legacy`` (the app's own workbook ingestion,
  kept for one release). Under ``dev-sqlite`` the default is ``legacy``, because
  sirdb lives in PostgreSQL.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
# The reference artifacts (M2C workbook, sir-configuration package) sit beside
# the application folder, not inside it.
WORKSPACE_ROOT = REPO_ROOT.parent

# Same precedence as components/llm/settings.py: the project-root .env wins.
for _candidate in (REPO_ROOT / ".env", REPO_ROOT / "config" / ".env"):
    if _candidate.exists():
        load_dotenv(_candidate, override=False)

AppEnv = Literal["dev-sqlite", "dev", "test", "uat", "prod"]
ReferenceSource = Literal["sirdb", "legacy"]


class ConfigError(RuntimeError):
    """The environment describes a configuration the platform refuses to run with."""


def sqlalchemy_url(url: str) -> str:
    """Use the psycopg (v3) driver for plain ``postgresql://`` URLs."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    app_env: AppEnv = Field(default="dev", validation_alias=AliasChoices("APP_ENV"))
    database_url: str = Field(default="", validation_alias=AliasChoices("CCRE_DATABASE_URL"))
    # The sirdb schema normally lives in the app database. A separate URL is only
    # needed when the app database is not PostgreSQL (dev-sqlite reading sirdb).
    sirdb_url: str = Field(default="", validation_alias=AliasChoices("CCRE_SIRDB_URL", "SIRDB_DATABASE_URL"))
    reference_source: Optional[ReferenceSource] = Field(default=None,
                                                        validation_alias=AliasChoices("REFERENCE_SOURCE"))
    data_dir: Path = Field(default=REPO_ROOT / ".ccre_data", validation_alias=AliasChoices("CCRE_DATA_DIR"))
    reference_dir: Path = Field(default=WORKSPACE_ROOT / "Reference",
                                validation_alias=AliasChoices("CCRE_REFERENCE_DIR"))
    # The advisory layer is optional. Switched off, the platform still ingests,
    # validates, gates and exports -- it simply offers no drafts.
    agents_enabled: bool = Field(default=True, validation_alias=AliasChoices("CCRE_AGENTS_ENABLED"))
    echo_sql: bool = Field(default=False, validation_alias=AliasChoices("CCRE_ECHO_SQL"))

    @field_validator("app_env", mode="before")
    @classmethod
    def _lower(cls, v: object) -> object:
        return v.strip().lower() if isinstance(v, str) else v

    @field_validator("reference_source", mode="before")
    @classmethod
    def _empty_is_default(cls, v: object) -> object:
        return (v.strip().lower() or None) if isinstance(v, str) else v

    @model_validator(mode="after")
    def _database_policy(self) -> "Settings":
        url = self.database_url
        if not url:
            if self.app_env != "dev-sqlite":
                raise ConfigError(
                    f"CCRE_DATABASE_URL is required (APP_ENV={self.app_env}); PostgreSQL is the default "
                    "database. Set APP_ENV=dev-sqlite for the offline SQLite mode.")
            self.data_dir.mkdir(parents=True, exist_ok=True)
            object.__setattr__(self, "database_url", f"sqlite:///{(self.data_dir / 'ccre_v2.db').as_posix()}")
        elif url.startswith("sqlite"):
            if self.app_env == "prod":
                raise ConfigError("SQLite is refused when APP_ENV=prod; use PostgreSQL.")
            if self.app_env != "dev-sqlite":
                raise ConfigError(f"SQLite is only allowed with APP_ENV=dev-sqlite (APP_ENV={self.app_env}).")
        else:
            object.__setattr__(self, "database_url", sqlalchemy_url(url))
        if self.reference_source is None:
            object.__setattr__(self, "reference_source", "legacy" if self.is_sqlite else "sirdb")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def sirdb_sqlalchemy_url(self) -> str:
        """Where the sirdb schema is read: its own URL if given, else the app database."""
        if self.sirdb_url:
            return sqlalchemy_url(self.sirdb_url)
        if self.is_sqlite:
            raise ConfigError("REFERENCE_SOURCE=sirdb needs PostgreSQL: set CCRE_DATABASE_URL to PostgreSQL "
                              "or CCRE_SIRDB_URL to the sirdb database.")
        return self.database_url


def load_settings() -> Settings:
    return Settings()


SETTINGS = load_settings()

# Processing level is IMP_CLR for every row observed in the config package;
# export clearance is not configured upstream yet.
DEFAULT_PROC_LVL = "IMP_CLR"
