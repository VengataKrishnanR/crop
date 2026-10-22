# Rule configuration: how it works

*CCRE Onboarding Platform, step 3 "Rule config + DMG". Written 12-10-2026.*

This document explains how a country requirement becomes rows in the M2C workbook, and how the platform checks that CCRE can actually raise it. Part A is for business and project readers. Part B is for the CCRE team and developers. Part C works through two real examples.

---

## Part A — In business terms

### A1. What rule configuration is for

A country (for example Bulgaria) wants DHL to ask the customer for a document or some information (for example the IOSS number) when certain shipments arrive. **Rule configuration** is where the CCRE team turns that approved business requirement into configuration that CCRE (the Customs Clearance Rule Engine) can run.

The configuration lives in **two files that work together**:

| | The M2C workbook | The config package ("beta file") |
|---|---|---|
| Answers | **When** to ask | **What** to ask |
| Example | "BG, consumer shipment, not duty-paid → ask for IOSS" | "IOSS for BG = the IOSSBG form, with these fields, written to these places in the shipment message" |
| Maintained by | The CCRE team | Support / GCCP, released as `sir-configuration-v….zip` |
| In the platform | Edited in step 3 | Uploaded and activated by an admin (Admin → Beta files) |

A rule can only work if **both** files agree. A rule in the workbook that points at something the package does not contain triggers, but has nothing to raise. That is called a **package gap**.

### A2. Where it sits in the onboarding

```
1 Requirement   business writes it (M2C columns, pick-lists, conditions) → CCRE consultant approves
                ("can this be configured in CCRE?")
2 Timeline      PM plans and approves the dates
3 Rule config   CCRE team builds the M2C rows + DMG email            ◄── this document
4 Sanity check  six automatic checks; CCRE approves or sends back
5–9             UAT test cases, execution, sign-off, go-live
```

### A3. What the CCRE team does in step 3

1. **Start the M2C draft.** The platform copies the country's existing rows from the loaded workbook, so the team edits what is live instead of retyping it.
2. **Get the rows to say what the business asked for.** Three ways:
   - **Rows from the requirement:** one click creates a row per requirement group, filled from the approved requirement (region, B2B/B2C, dates, product codes, value and weight limits, conditions).
   - **Align with the requirement:** copies the requirement's values onto an existing row, keeping its group and definitions.
   - **Edit the row by hand,** or let the AI propose rows from the requirement. AI proposals are only applied when someone accepts them.
3. **Write the condition (Other Logic)** with the condition builder (service code, incoterm, origin country, short code such as SDT, HS code) or pick from the workbook's palette. Every condition is checked before it can be used.
4. **Say what is asked for (SIR Reference).** For each row, bind the requirement definition from the config package. Optionally pick only some of its fields, and set *waived to validate*, *waived if whitelisted* and *only if service code*.
5. **Look at three views of the result:**
   - **Changes vs workbook:** exactly what changes in the M2C, field by field (new / changed / removed rows).
   - **Package coverage:** whether the active config package contains every group and definition the rows use for this country. If not, **Package request (.csv)** produces the request for Support.
   - **Validate & download:** the 16 automatic checks, the same six checks the sanity check runs (as a preview), and the generated M2C workbook (.xlsx).
6. **Complete the DMG email task:** the email that asks the DMG team to send the needed data. It is reviewed by a second CCRE person, or marked not required.
7. **Submit for the sanity check.**

### A4. What stops the team, and what does not

| Situation | Effect |
|---|---|
| A row has an **error** (min above max, expiry before effective date, condition that does not parse, no requirement group, binding without a definition) | **Submit is blocked** until it is fixed |
| A row needs something the **config package does not have** (package gap) | Submit is **allowed**: Support has to fix the package, not the CCRE team. The **sanity check** then fails until the package covers it, or a CCRE consultant accepts it as an exception with the Support ticket number |
| A **warning** (value not in the workbook's lists, no definition bound yet, hand-typed key) | Shown, never blocks |
| DMG email task not completed | Submit is blocked |

### A5. Why the rows match the requirement

The requirement is captured as the same columns the M2C has (step 1). The platform then:
- copies the business's values into the rows ("Rows from the requirement" / "Align"),
- in the sanity check, compares every requirement group with its row **field by field** and shows any difference ("requirement says 15-11-2026, M2C says 01-01-2021").

Test cases are written from the requirement, so a row that says something else would make UAT fail for the wrong reason. This comparison catches it before UAT starts.

---

## Part B — In technical terms

### B1. The two files and how they connect (verified on the real files)

```
M2C workbook                                    Config package (beta file)
────────────                                    ──────────────────────────
Import row  (WHEN)                              ShpInfReqGrpDef.csv           group id, code, name
  Country, B2B/B2C, dates, products,            ShpInfReqDefInShpInfReqGrpDefOfCtryProc.csv
  DV/IV, currency, min/max value & weight,        country · IMP_CLR · group id → definition id
  Other Logic, hold codes                       sir definitions/<definition id>.json
  P  Document Reference        ──┐                definition: name, component, Ent[] (nested ≤7)
  Q  SIRG Document Reference  ─┐ │                  → Att[] (fields) → AttMsgPos (message position)
     = Country|Import|GroupCd  │ │
                               │ │   join keys
SIR Reference row (WHICH FIELDS)│ │
  A  Document Reference    ◄────┼─┘  legacy rules: A = Import.P
  B  SIR Document Reference◄───┘     SIRG rules: first 3 parts of B = Import.Q
     = Country|Import|GroupCd|CmptNm
  G  SIR Technical Id  ─────────────────────────► definition id (= JSON file name)
  H  AttributeID (&&-joined) ───────────────────► Att.Id inside that JSON
  I  (no header) attribute labels, aligned with H
Technical SIRG / Technical SIR tabs: copies of the package's mapping and definition list
```

- `Import` in a reference means processing level **`IMP_CLR`**; the package has no other level.
- The **lookup key** into the package is *(country, IMP_CLR, group code)*. In the workbook's copy it is unique, except one exact duplicate record (AU · GSTE).
- **Component names (CmptNm) are not unique** (e.g. `PPYComposed` × 31), so nothing keys on them.

### B2. Data model (application database)

| Table | Holds | Notes |
|---|---|---|
| `rule_set` | A set of M2C rows | `case_id IS NULL` = workbook **baseline** (from *Load M2C workbook*); `case_id` set = that onboarding's **draft**. Newest per case is the working draft |
| `rule` | One **Import** row | `region, ctry_cd, direction, shipment_type, effective_date, expiry_date, network_product_codes, value_basis, currency, min_value, max_value, min_weight, max_weight, other_logic, country_hold_cd, global_hold_cd, sirg_cd, doc_reference, row_no` |
| `rule_binding` | One **SIR Reference** line of a rule | `sir_id` (col G), `cmpt_nm` (F), `attribute_ids` (H, list), `waived_if_whitelisted` (C), `waived_to_validate` (D), `check_service_code` (E), `sirg_cd/sirg_id` |
| `sirg_def`, `sir_def`, `sir_attribute`, `ctry_proc_mapping` | The config package catalog | Keyed by **(id, package_version)**, so several packages coexist |
| `package_upload` | Uploaded beta files | Status REVIEWED / ACTIVE / SUPERSEDED / REJECTED, with the automatic review |
| `mirror_sirg`, `mirror_sir`, `permitted_value`, `expression_template` | Workbook copies of Technical SIRG / Technical SIR, the Validation lists, the Other Logic palette | Used for drift checks, dropdowns and the palette |
| `audit_event` | Every edit | `m2c:row_added / row_edited / row_duplicated / row_removed / binding_added / binding_edited / binding_removed / row_from_requirement / row_aligned_to_requirement` |

**Which package is used:** `tools.core.packages.active_package_version()` returns the version an admin activated. Before any activation it falls back to the most recently loaded package. Every check calls this one function: row checks, coverage, the sanity check, validation and the agent tools.

### B3. Loading the workbook (how rows and bindings are created)

`tools/ingestion/workbook.py → ingest_workbook()`:
1. One `rule` is created per Import row. `sirg_cd` is the third part of `SIRG Document Reference` when it has three parts and is not a `TEST` placeholder.
2. SIR Reference lines are attached to rules by **either** documented join:
   - **Legacy (hold-code rules):** `SIR Reference.Document Reference == Import.Document Reference`
   - **SIRG rules:** the first three parts of `SIR Reference.SIR Document Reference` == `Import.SIRG Document Reference`

   `TEST` placeholders never join. A `TBD` hold code inside an otherwise real key still joins (IL rows 32–33).
3. On the current workbook every Import row gets its lines, and 8 SIR Reference lines are used by no rule: rows 33, 52–56, 59 and 60.

### B4. Starting the draft

`tools/workflow/case_facts.py → start_m2c_draft()` (endpoint `POST /m2c/start`, state RULE_CONFIG, CCRE roles):
- It creates `rule_set(case_id=…, version='v0.1')`.
- It copies every baseline `rule` of the country with all its `rule_binding`s, **keeping `row_no`**. That row number is how changes are later matched back to the workbook.
- It is idempotent: an existing draft is returned unchanged.

### B5. Editing (endpoints, all audited)

Writes require state **RULE_CONFIG**, an unsealed draft, and role CCRE_TEAM / CCRE_CONSULTANT / ADMIN. Each write answers with the row's **fresh checks**.

| Endpoint | Does |
|---|---|
| `GET /onboardings/{id}/rule-config` | The workspace: rows with status (ok / warning / package / error) and issues, summary counts, dropdown options (workbook lists, groups mapped for the country first) |
| `POST …/rows` · `PUT …/rows/{rid}` · `POST …/rows/{rid}/duplicate` · `DELETE …/rows/{rid}` | Add / edit / duplicate (with bindings) / remove a row. Codes are upper-cased; empty strings become NULL |
| `POST …/rows/from-requirement` | One row per requirement group from the requirement's `m2c_row` |
| `POST …/rows/{rid}/align-requirement` | Copies `m2c_row` onto the row; group and bindings stay |
| `POST …/rows/{rid}/bindings` · `PUT/DELETE …/bindings/{bid}` | Bind a definition. `cmpt_nm` and `sirg_id` are taken from the package; attribute IDs are checked to exist **inside that definition**; the same definition cannot be bound twice |
| `GET …/definitions?q=&group=` | Search definitions in the active package; the group's own mapped definitions first, then mapped for the country, then the rest |
| `GET …/definitions/{sir}/attributes` | The definition's fields (walked through nested `Ent[]`) with mandatory flag and message positions |
| `POST …/condition` · `GET …/palette` | Condition builder; workbook palette entries, each grammar-checked |
| `GET …/changes` · `GET …/coverage` · `GET …/coverage.csv` · `GET …/m2c.xlsx` | Changes vs workbook, package coverage, Support request, generated workbook |

### B6. Row checks (`tools/ruleconfig.py → row_issues`)

Three levels:
- **error** blocks submitting.
- **package** means the package is missing something; it is gated at the sanity check.
- **warning** is information only.

| Level | Check |
|---|---|
| error | Row country ≠ the onboarding's country |
| error | `min_value > max_value`; `min_weight > max_weight` |
| error | A value band without a currency |
| error | `expiry_date < effective_date` |
| error / warning | Other Logic: the platform grammar (`tools/core/grammar.analyse`) — parse errors, and logic traps such as unparenthesised `&&` / `\|\|` |
| error | No requirement group (`sirg_cd` empty) |
| error | A binding without a definition ID |
| package | Group not in the active package; group not mapped for the country |
| package | Bound definition not shipped by the package; not mapped to the group for the country |
| warning | Region / currency / B2B/B2C / DV/IV not in the workbook's Validation lists |
| warning | DV/IV set but no value band |
| warning | No definition bound (SIR Reference empty for the row) |
| warning | Document Reference typed by hand and different from the generated key |

**Gate:** the transition `request_sanity_check` has `requires_rows_clean` (number of draft rows with an **error** = 0) and `requires_dmg_complete`. See `tools/workflow/state_machine.py` and `case_facts.gate_context`.

### B7. Keys are generated, never typed

- **Document Reference** = `Country|Direction|CountryHold|GlobalHold` (`Rule.generated_doc_reference`). This is what the workbook's `=CONCATENATE(B,"|Import|",N,"|",O)` produces.
- **SIRG Document Reference** = `Country|Import|GroupCd`.
- **SIR Document Reference** = `Country|Import|GroupCd|CmptNm`.

Because keys are generated, inserting or removing a row can never re-point a link. In the workbook the links are positional: `=IF(Import!P<n>…)`.

### B8. Conditions (Other Logic)

The builder turns choices into the rule language and checks the result with the same grammar the validator uses:

| Choice | Produces |
|---|---|
| Service code has any of DD, DS | `serviceCodeList.contains("DD") \|\| serviceCodeList.contains("DS")` |
| Service code has none of DD | `!serviceCodeList.contains("DD")` |
| Incoterm is one of DDP | `incotermCodeList.contains("DDP")` |
| Origin country is none of CN | `OriginCountry!="CN"` |
| Short code SDT is present | `matchCiMask("shortCode\|==\|SDT","value\|!=\|<blank>")` |
| Inbound HS code is blank | `hscode("inboundHsCode","<blank>")` |

**Joining:**
- Several clauses are joined with `&&` or `||`. A clause that already contains `&&` / `||` is put in brackets.
- At intake, rows inside one condition group are joined with `||` and groups with `&&`.
- **Other Logic is never executed by the platform;** it is only parsed and checked.

### B9. From the requirement to the row

The requirement stores `structured.m2c` (the business answers) and `structured.m2c_row` (the row they give), produced by `tools/intake_fields.to_m2c()`:
- The workbook's thresholds are inclusive (`>=` / `<=`), so strict operators are converted: `> 150` → `150.01`, `< 1000` → `999.99`. This matches what the workbook already contains (50.01, 999.99).
- Value and weight conditions fill `min/max_value`, `value_basis`, `currency`, `min/max_weight`. All other conditions become `other_logic`.
- "Not applicable" answers become empty columns.

*Rows from the requirement* creates rows from `m2c_row`, one per requirement group. *Align* applies `m2c_row` to an existing row.

### B10. Changes vs workbook (`changes()`)

- Draft rows are matched to the country's baseline rows by **`row_no`**.
- A draft row with no `row_no` is **NEW**. A baseline row with no draft partner is **REMOVED**. A matched row is **CHANGED** when any of the 16 business fields differs (`RULE_FIELDS`, compared value by value), or when its bindings differ (definition, group, waivers, service code, attribute set). Otherwise it is **UNCHANGED**.

### B11. Package coverage (`coverage()`)

For every *(group, definition)* the country's rows use, it checks against the **active** package:
- the group is in `sirg_def`;
- the definition is in `sir_def`;
- `ctry_proc_mapping` has *(country, group, definition)*;
- if no definition is bound yet, the group is mapped for the country.

Anything missing is listed, and `coverage.csv` writes the Support request in the package's own mapping format: `CtryProc.DhlCtryCd, CtryProc.ProcLvlCd, ShpInfReqGrpDef.Cd, ShpInfReqGrpDef.Id, ShpInfReqDef.Id, ShpInfReqDef.CmptNm, Needed`.

### B12. The generated M2C workbook (`build_m2c_workbook()`)

| Sheet | Content |
|---|---|
| Import | The country's draft rows in Import column order; dates `DD-MM-YYYY`; column P = `=CONCATENATE(B<n>,"\|Import\|",N<n>,"\|",O<n>)`; column Q = `Country\|Import\|Group` |
| Export | Header only (as in the workbook) |
| SIR Reference | One line per binding: A = `=IF(Import!P<n><>0,Import!P<n>,"")`, pointing at **its own row**, so the position is always right; B = `Country\|Import\|Group\|CmptNm`; C/D Y/N; E service code; F CmptNm; G definition ID; H attribute IDs joined with `&` |
| Technical SIR / Technical SIRG | The definitions and mappings the draft uses, filled from the active package |
| Other Logic | The palette |
| Validation | The permitted-value lists |
| Changes (platform) | Every new / changed / removed row and field: what to review before loading |

### B13. The sanity check that follows (step 4)

Entering step 4 runs six checks automatically and saves the run with a **fingerprint**: a hash of the country's rows and bindings, the requirement version, DMG status, package version and accepted exceptions.

1. Rows complete (B6 errors)
2. **Rows match the requirement:** per requirement group, the closest row compared field by field
3. Rules pass the 16 validation checks (package checks excluded)
4. The package can raise every requirement (B11)
5. DMG email task completed
6. Changes (information)

Approval needs a **passing run whose fingerprint still matches**: change a row and the check must run again. A CCRE consultant may accept a package gap or a deliberate difference from the requirement as an exception, with a reason and a reference.

### B14. Supporting tools

- **Admin → Beta files:** upload, automatic review (zip safety, structure, version, internal consistency, drift against the workbook, changes against the active package), activate.
- **Reference page:** trace one country + group through every link listed in B1, with ✓ / ✕, the fields and their message positions, and a per-country drift table (workbook vs active package).
- **Requirement form:** offers only the groups the active package maps for the country, with their definitions, so a package gap cannot be created at intake by accident.

---

## Part C — Two real examples

### C1. DE · Power of Attorney (configurable, but the files disagree)

| Link | Value |
|---|---|
| Import row 38 | DE · B2C · `incotermCodeList.contains("DDP")` · Q = `DE\|Import\|POA` |
| Workbook Technical SIRG row 613 | DE · IMP_CLR · POA → **DEPOA**, definition `b5a141ed…` |
| SIR Reference row 84 | `DE\|Import\|POA\|DEPOA` → definition `b5a141ed…`, label *Power of Attorney*, waived if whitelisted = Y |
| Package 2.10.4-beta.2 | Group POA `dfb77196…` mapped for DE → definition **`1595f691…`** ("Power of Attorney - DE", 6 fields) |
| Result | CCRE can raise POA, but the workbook points at a **newer** definition (`b5a141ed…`) that this package does not ship. Coverage and sanity report the gap; the Reference page shows "workbook and package point at different definitions". The workbook's Sheet1 is an exact copy of the package's old mapping row |

### C2. BG · IOSS (package gap)

| Link | Value |
|---|---|
| Import row 57 | BG · B2C · `!serviceCodeList.contains("DD")` · Q = `BG\|Import\|IOSS` |
| Workbook Technical SIRG | BG · IMP_CLR · IOSS → **IOSSBG**, definition `af262af3…` |
| SIR Reference row 86 | `BG\|Import\|IOSS\|IOSSBG` → `af262af3…`, whole definition (no field list) |
| Package 2.10.4-beta.2 (released 21-10-2025) | **No IOSS group, no BG mapping row, no `af262af3….json`.** BG has no mappings at all in this package |
| Result | The rule is valid. Coverage lists the missing mapping and downloads the Support request. The sanity check fails "The config package can raise every requirement" until a newer beta file (2.10.9-beta.2 or later) is uploaded and activated, or a consultant accepts the gap with the Support ticket |

---

## Glossary

| Term | Meaning |
|---|---|
| **M2C** | The rule workbook: Import rules plus reference tabs |
| **SIRG** | Shipment Information Requirement **Group**, e.g. IOSS, POA (`ShpInfReqGrpDef`) |
| **SIR** | Shipment Information Requirement **definition**: one form with fields (`ShpInfReqDef`, one JSON file) |
| **Attribute / field** | One item of a definition, with its message position (`AttMsgPos`: XPath / JSONPath in the shipment message) |
| **Binding** | One SIR Reference line: which definition, and optionally which fields, a rule asks for |
| **Config package / beta file** | Support's `sir-configuration-v….zip`; the platform uses the **active** one |
| **Package gap** | The rule needs a group or definition the active package does not map for the country |
| **Baseline / draft** | The country's rows as in the loaded workbook / the onboarding's working copy |
| **IMP_CLR** | Import clearance, the processing level behind "Import" in references |
