# Developer entry points. On Windows without make, use scripts/test-pg.ps1 and
# `python scripts/migrate.py` directly.

PY ?= $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || ([ -x .venv/Scripts/python.exe ] && echo .venv/Scripts/python.exe) || echo python3)

.PHONY: test test-pg migrate parity

## Fast suite: in-memory SQLite, legacy reference source, stub LLM.
test:
	CCRE_LLM_MODE=stub $(PY) -m pytest tests -q

## Full suite on PostgreSQL: a Testcontainers postgres:16.4, or an existing server via
## CCRE_TEST_PG_URL (a throw-away database is created there and dropped afterwards).
test-pg:
	CCRE_LLM_MODE=stub CCRE_TEST_PG=1 $(PY) -m pytest tests -q

## Apply app (Alembic) and sirdb migrations to CCRE_DATABASE_URL.
migrate:
	$(PY) scripts/migrate.py

## Legacy ingestion vs sirdb, field by field, on CCRE_DATABASE_URL.
parity:
	$(PY) scripts/reference_parity.py
