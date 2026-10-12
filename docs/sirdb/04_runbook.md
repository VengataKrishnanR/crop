# Runbook — SIR/SIRG reference database

Run every command from `ccre-onboarding-agent\` with the virtual environment active (`.venv\Scripts\activate`).

## 1. One-time setup

1. **Install Docker Desktop and start it.**
2. **Set the credentials.** Copy `deploy\sirdb.env.example` to `deploy\sirdb.env` and choose a user and a strong password. Put the same values into `SIRDB_DATABASE_URL`. `deploy\sirdb.env` is git-ignored, so never commit it.
3. **Start PostgreSQL 16:**
   ```
   docker compose -f deploy/sirdb-compose.yml --env-file deploy/sirdb.env up -d
   docker inspect -f "{{.State.Health.Status}}" ccre-sirdb        # → healthy
   ```
4. **Install the driver:**
   ```
   pip install -r requirements.txt
   ```
   This installs `psycopg[binary]`.

The tools read `SIRDB_DATABASE_URL` from the environment and fall back to `deploy\sirdb.env`. Messages show the URL with the password hidden.

## 2. Create or upgrade the schema

```
python -m tools.sirdb.migrate --status     # pending migrations
python -m tools.sirdb.migrate              # apply them (each in its own transaction)
```

Re-running is safe. A migration that changed after it was applied is refused: add a new `000N_*.sql` instead.

## 3. Profile a workbook (read-only)

```
python -m tools.sirdb.profile "..\Reference\M2c_….xlsx" --out docs/sirdb/generated
```

Writes `profile.json` and `reconciliation.md`, listing every finding with sheet and row. The workbook is never written to. If Excel has it open, profile a copy.

## 4. Load a workbook

```
python -m tools.sirdb.loader "..\Reference\M2c_….xlsx" --report docs/sirdb/generated
```

- Prints the batch id and the per-sheet reconciliation: source rows, mapped, unmapped, cells, formulas, warnings, errors. With `--report` it also writes `load_reconciliation.md`.
- **The same file again** prints `ALREADY_LOADED`, and nothing changes.
- **A newer workbook** becomes a new batch and the **current** one. Use `--keep-current` to load it without switching. Earlier batches stay as history.

## 5. Resolve, validate, export

```
python -m tools.sirdb.resolve resolve DE POA          # SIRG → component → SIR + SIR Reference lines
python -m tools.sirdb.resolve validate rule.json      # blocking errors vs warnings for a proposed rule
python -m tools.sirdb.resolve export import.xlsx      # the final Import dataset (17 columns); .csv works too
```

`rule.json` example:

```json
{"country": "DE", "sirg_cd": "POA", "region": "EU", "shipment_type": "B2C",
 "effective_date": "15-11-2026", "currency": "EUR", "value_basis": "DV", "min_value": 150,
 "other_logic": "incotermCodeList.contains(\"DDP\")"}
```

From Python, proposals go through `save_proposal` (status VALIDATED or DRAFT) and then `approve_proposal`. Approval re-validates against the current batch and refuses while any blocking error remains. Approved proposals appear in `v_import_final`.

## 6. Tests

```
python -m pytest tests/test_sirdb.py -q
```

The tests create a throw-away database per run (`sirdb_test_xxxxxxxx`) and drop it afterwards. They skip when PostgreSQL or the workbook is not available. If the workbook is open in Excel, set `CCRE_REFERENCE_DIR` to a folder with a copy.

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Set SIRDB_DATABASE_URL` | No URL in the environment or `deploy\sirdb.env` | Create `deploy\sirdb.env` from the example |
| `connection refused` on port 55432 | Container not running | `docker compose -f deploy/sirdb-compose.yml --env-file deploy/sirdb.env up -d`; start Docker Desktop first |
| `PermissionError` reading the workbook | Excel has it open (locked) | Close it, or copy it and load the copy (same hash) |
| `Migration … changed after it was applied` | A migration file was edited | Revert the edit; put the change in a new migration |
| `… is append-only` | Something tried to change a source row | Source data never changes: load a new workbook as a new batch |
| Resolver says `NOT_FOUND` | No Technical SIRG row for the country + SIRG code | Reference-data maintenance (a new package / SIRG mapping), not a code fix |
| Resolver says `AMBIGUOUS` | Several different SIRG rows for one key | A person decides which applies; correct the source workbook |
| `No current batch` | Nothing loaded yet | Run the loader |

## 8. Reset (local only)

This deletes everything in the local database:

```
docker compose -f deploy/sirdb-compose.yml --env-file deploy/sirdb.env down -v
```

Then repeat sections 1.3, 2 and 4.
