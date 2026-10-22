# SIR/SIRG reference database

This is the foundation for generating the M2C **Import** sheet from approved business choices plus the SIR/SIRG reference data. The downstream application consumes only the final Import-format dataset, `sirdb.v_import_final`.

| # | Document | Contents |
|---|---|---|
| 1 | [01_workbook_analysis.md](01_workbook_analysis.md) | Inventory, the three generations of Import rows, field-level data dictionary, row traces, Document Reference vs SIRG Document Reference, open questions Q-01…Q-13 |
| 2 | [02_design.md](02_design.md) | Layers, ER diagram, source-to-target mapping for every Import column, resolution flow, validation rules, batch and re-import policy |
| 3 | [03_sql_examples.md](03_sql_examples.md) | The key lookups, reconciliation queries, Import generation, version comparison |
| 4 | [04_runbook.md](04_runbook.md) | Setup, environment variables, migrations, load, validation, export, tests, troubleshooting |
| — | [generated/reconciliation.md](generated/reconciliation.md) | Every finding with sheet, row and column (from the profiler) |
| — | [generated/load_reconciliation.md](generated/load_reconciliation.md) | Per-sheet load reconciliation of the last load |

Code: `tools/sirdb/` (workbook reader, profiler, migrator, loader, resolver) · `migrations/sirdb/` · `deploy/sirdb-compose.yml` · `tests/test_sirdb.py`.

## What was actually run

All of this ran on 12-10-2026:
- PostgreSQL 16.4 in Docker (`ccre-sirdb`) was started.
- All 5 migrations were applied.
- The workbook (SHA-256 `8a8ad95e…f393`) was loaded as batch 1, and a reload was a no-op.
- Every source row of every sheet is stored: 0 unmapped.
- The exported final Import equals the workbook's Import sheet: 0 cell differences.
- `tests/test_sirdb.py` passed: 25 tests.
