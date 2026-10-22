# ADR 0003 — PostgreSQL with `app` and `sirdb` schemas; sirdb as the single source of reference data

- Status: Accepted
- Date: 22-10-2026
- Context documents: `docs/design/production-design.md` ("Key design decisions" rows 2, 3, 6;
  "Data architecture"); `docs/sirdb/`

## Context

The application ran on a SQLite file with no migrations, and read the M2C workbook twice: once
through its own ingestion (`tools/ingestion/workbook.py` into `rule`, `mirror_*`,
`permitted_value`, `expression_template`) and once through `sirdb` (a PostgreSQL schema with its own
loader, resolver and a 0-difference round trip). Two parsers of one workbook drift. SQLite also hides
defects PostgreSQL enforces: the first PostgreSQL run of the suite rejected a 37-character
`sir_def.derived_from_id` (a GUID with a stray trailing character in package 2.10.4-beta.2) that
SQLite had stored silently.

## Decision

1. **One PostgreSQL database, two schemas.** `app` (application tables) and `sirdb` (reference).
   Alembic owns `app` (`migrations/app`: 0001 reproduces the models, 0002 adds locking and the
   package pin); the sirdb SQL migrations 0001–0005 are unchanged. `scripts/migrate.py` runs both, in
   that order, once per deploy. A test checks the migrated schema equals the models.
2. **Typed settings, PostgreSQL by default.** `tools/core/config.py` (pydantic-settings).
   `CCRE_DATABASE_URL` is required; SQLite is allowed only with `APP_ENV=dev-sqlite` and refused when
   `APP_ENV=prod`. On SQLite the `app` schema is translated away, so one model serves both.
3. **Reference data through one repository.** `tools.reference.get_reference(session)` returns a
   `ReferenceRepository`; `SirdbReferenceRepository` (default) reads `sirdb.v_import_final`,
   `v_import_rule_sir_reference` and the current batch's catalogue tables;
   `LegacyReferenceRepository` (`REFERENCE_SOURCE=legacy`) reproduces the old queries for one release.
   Intake pick-lists, rule configuration, sanity checks, the validation snapshot, the M2C draft seed
   and the agent tools all go through it. A test fails if any other module reads the ingestion
   tables or the workbook parser. Both return the same frozen value types, so parity is checked field
   by field (`tools/reference/parity.py`, `scripts/reference_parity.py`).
4. **Optimistic locking.** `row_version` (`version_id_col`) on `onboarding_case`, `rule_set`, `rule`
   and `uat_test_case`. A stale write raises `StaleDataError`, answered with **409** by an app-wide
   handler. The transition endpoint also honours `If-Match: <row_version>`; the case summary returns
   `row_version`. (Named `row_version` because `rule_set.version` is already the business version.)
5. **Package pin.** `onboarding_case.package_version` and `package_hash` are set when the M2C draft
   starts (configuration time): the active package version and the SHA-256 of its upload (empty when
   the package was loaded by CLI).
6. **Tests in two modes.** `pytest`: in-memory SQLite, legacy source — fast and offline. `make test-pg`
   (`scripts/test-pg.ps1`): the same suite on PostgreSQL via Testcontainers, or on an existing server
   (`CCRE_TEST_PG_URL`) in a throw-away database, plus migration, sirdb and parity tests. Per-test
   isolation on PostgreSQL deletes all app rows (`DELETE`, not `TRUNCATE`, which deadlocks behind a
   session left idle in a transaction).

## Parity result (workbook `2.10.9-beta.2`, package `2.10.4-beta.2`)

Equal: 56 Import rows (every field), 984 Technical SIR rows, all Technical SIRG rows, the Validation
lists, the 5 Other Logic entries. Accepted differences:

| Code | What | Decision |
|---|---|---|
| `EXPORT_ROWS` | Legacy also loads Export-sheet rows; sirdb loads Import only (0 rows in this workbook) | Import only, per design decision 7 |
| `PROPOSAL_ROWS` | sirdb adds APPROVED platform proposals to `v_import_final` | Expected |
| `TBD_KEY_ROWS` | IL Import rows 32/33 (`IL\|Import\|TBD\|CIDM`, `…\|TBD\|CPA`): sirdb treats a `TBD` key as a placeholder and joins no SIR Reference line; legacy joined lines 50/51, which have no SIR id | Keep sirdb. Rule configuration reports a TBD hold code as a blocking error, so the row cannot be submitted until the hold code is decided |

## Consequences

- Behaviour changes, all deliberate: intake pick-lists, the condition-builder palette and
  `find_similar_rules` / `search_m2c_rows` read baseline reference rows only, no longer other cases'
  drafts; a TBD hold code is now a row error.
- Running locally without PostgreSQL needs `APP_ENV=dev-sqlite` (set in `config/.env.stub`).
- The legacy ingestion and `REFERENCE_SOURCE=legacy` are removed in the release after the pilot
  confirms sirdb in use.
- Package catalogue tables (`sirg_def`, `sir_def`, `ctry_proc_mapping`, …) stay in `app`; they are not
  workbook data and are not part of this repository.

## Rejected alternatives

- **Keep SQLite in production** — no concurrency control, no HA, no PITR, and it hid a real data defect.
- **Two databases (app, sirdb)** — two backup/restore stories and no transactional reads across them.
- **Align sirdb with the legacy TBD join** — would change the loader and its documented placeholder
  rule to reproduce a join to lines that carry no SIR id.
