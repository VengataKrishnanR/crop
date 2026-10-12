# How the database is planned

One relational database holds everything the platform knows. It runs on **SQLite** today (`.ccre_data\ccre_v2.db`) and moves to **PostgreSQL** by changing one setting, `CCRE_DATABASE_URL`. All access goes through SQLAlchemy, so no code changes.

Tables are created automatically on start. New tables appear in an existing database by themselves. A **new column on an existing table** needs a migration, so use Alembic before going to production.

## The seven areas

```
 ┌─────────────────────────┐   ┌──────────────────────────┐
 │ 1 Reference catalogue   │   │ 2 Rules (the M2C)        │
 │ config_package          │   │ rule_set ─< rule ─< rule_binding
 │ sirg_def · sir_def      │◄──┤ (sirg_cd / sir_id point  │
 │ sir_attribute           │   │  into the catalogue)     │
 │ ctry_proc_mapping       │   └────────────┬─────────────┘
 │ release_note_entry      │                │ draft = rule_set.case_id
 │ mirror_sir · mirror_sirg│   ┌────────────▼─────────────┐
 │ permitted_value         │   │ 3 Onboarding lifecycle   │
 │ expression_template     │   │ onboarding_case (state)  │
 └─────────────────────────┘   │  ├─< requirement, intake_message
                               │  ├─< timeline ─< milestone
 ┌─────────────────────────┐   │  ├─< approval, audit_event
 │ 7 People & settings     │   │  ├─< dmg_task  (+ dmg_template)
 │ app_user (roles,        │   │  ├─< sanity_run, sanity_waiver
 │   countries, hashed pw) │   │  ├─< validation_run, proposed_change
 │ mail_settings (enc. pw) │   │  └─< uat_test_case
 │ notification (sent log) │   └────────────┬─────────────┘
 │ execution_endpoint      │                │
 │   (enc. credential)     │   ┌────────────▼─────────────┐
 └─────────────────────────┘   │ 4 UAT                    │
                               │ uat_run ─< uat_result ─< uat_comparison
                               │ payload_template         │
                               └──────────────────────────┘
```

## 1. Reference catalogue: what exists (read-only, loaded from the files)

| Table | Holds | Key |
|---|---|---|
| `config_package` | One row per loaded sir-configuration package (e.g. 2.10.4-beta.2) | `version` |
| `sirg_def` | Requirement groups (SIRG): id, code, name | **(`id`, `package_version`)** |
| `sir_def` | Requirement definitions (SIR): name, component, country | **(`id`, `package_version`)** |
| `sir_attribute` | Every attribute of a definition, walked recursively through `Ent[]`, with its DMG message positions | `(sir_id, att_id, package_version)` |
| `ctry_proc_mapping` | Which groups and definitions a country is mapped to | per package version |
| `mirror_sir`, `mirror_sirg`, `permitted_value`, `expression_template` | The workbook's Technical SIR/SIRG, Validation lists and Other Logic palette | per workbook version |

The key includes the version on purpose: two package versions can be held side by side, which is what reviewing a new GCCP release needs. Attribute ids are only unique per definition, hence the compound key.

## 2. Rules: the M2C, owned by the platform

| Table | Holds |
|---|---|
| `rule_set` | A set of M2C rows. `case_id` empty = the workbook baseline; `case_id` set = that onboarding's **draft** |
| `rule` | One **Import** row: region, country, B2B/B2C, dates, product codes, DV/IV, currency, min/max value and weight, Other Logic, hold codes, group |
| `rule_binding` | Its **SIR Reference** lines: definition, waivers, service code, attribute ids |

Rows are linked by ids, not by the workbook's `CONCATENATE` strings and row offsets. The workbook is **generated** from these tables, with its formulas rebuilt, so inserting a row can never re-point a binding.

## 3. Onboarding lifecycle: one row per country onboarding

| Table | Holds |
|---|---|
| `onboarding_case` | Code, country, title, the **state** (the workflow position), dates (requested / approved / actual go-live) |
| `requirement` | Every version of the captured requirement. `structured` holds the M2C criteria (`m2c`), the check (`m2c_check`) and the row they give (`m2c_row`) |
| `intake_message` | The intake chat |
| `timeline`, `milestone` | Plan versions and the planned vs actual dates per stage |
| `approval` | Every approve / reject with role, comment and rule-set version |
| `audit_event` | **Append-only** log of everything (transitions, row edits, waivers, emails) |
| `proposed_change` | AI proposals, which are never applied until a person accepts them |
| `validation_run` | Saved results of the 16 deterministic checks |
| `dmg_task`, `dmg_template` | The DMG email per onboarding, and the CCRE-owned template |
| **`sanity_run`** | **New:** every sanity check run, with the full checklist as shown, the result and a fingerprint |
| **`sanity_waiver`** | **New:** a check accepted as an exception (package gap or deliberate difference), with reason, reference (Support ticket), who, when, and who revoked it |

### How the sanity tables work

- **`sanity_run.items`** stores the six checks exactly as the user saw them, findings included. That is the evidence, and **Report (.xlsx)** prints it.
- **`sanity_run.fingerprint`** is a hash of what was checked: the country's M2C rows and bindings, the requirement version, the DMG status, the package version and the active waivers. **Approving needs a passing run whose fingerprint still matches.** Change any row afterwards and the check must run again, so an approval always refers to the configuration that actually passed.
- **`sanity_waiver`** rows are never deleted: revoking sets `revoked_by` / `revoked_at`. Only `package` and `requirement_match` can be waived, and only by a CCRE consultant or admin.

## 4. UAT

| Table | Holds |
|---|---|
| `uat_test_case` | Each test case (AI-written or from a "+ scenario"), its status through CCRE and business approval |
| `payload_template` | Sample shipment payloads used to build requests |
| `uat_run`, `uat_result` | Each execution cycle and, per test, the request, response, verdict and failure analysis |
| `uat_comparison` | TEST-vs-UAT response comparisons |

## 7. People and settings

| Table | Holds |
|---|---|
| `app_user` | Users, role, countries (for business users), **PBKDF2-hashed** password |
| `mail_settings`, `notification` | SMTP settings (password **encrypted**), and every email sent or written to the outbox |
| `execution_endpoint` | UAT endpoints; the credential is **encrypted** (Fernet, key in `.ccre_data\secret.key`) and never returned to the browser |

## Design rules

1. **Evidence is kept, never overwritten.** Requirements, timelines and sanity runs are versioned; approvals and audit events are append-only; waivers are revoked, not deleted.
2. **Catalogue data is versioned** by package or workbook version, so drift between versions can be measured.
3. **The platform owns the rules; files are outputs.** The M2C workbook and the package request CSV are generated from the tables.
4. **JSON columns hold documents, relational columns hold facts.** Anything filtered or joined on (state, country, ids, status) is a column. Anything shown as a whole (checklists, findings, payloads) is JSON.
5. **Secrets are encrypted at rest and write-only** through the API.
