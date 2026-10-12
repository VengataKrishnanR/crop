# Phase 1 — Workbook analysis

**File analysed:** `Reference/M2c_6_5_ver_1_W29_2.10.9-beta.2_20262608-131409_20262409-100918_20262409-144825_20262409-162826 (2).xlsx`
**SHA-256:** `8a8ad95e442795d69dad1b558249c77e042be5308fcfa672ce43dfdded04f393` (130 750 bytes, saved 12-10-2026 18:08). It is the only M2C workbook in the project folder.

The analysis ran on a byte-identical read-only copy; the original was not opened for writing. To reproduce it:

```
python -m tools.sirdb.profile "<workbook>.xlsx" --out docs/sirdb/generated
```

The generator writes `generated/profile.json` and `generated/reconciliation.md`. The reconciliation lists every finding with sheet, row and column: **333 findings, 0 errors, 97 warnings, 236 info**.

Labels used below: **[F]** verified fact (checked against the cells) · **[I]** inference (evidence given, not confirmed) · **[Q-nn]** open question.

---

## 1. Inventory

| Sheet | Used range | Data rows | Cols | Formula cells | Notes |
|---|---|---|---|---|---|
| Import | A1:Q57 | 56 | 17 | 33 (all in P) | Filter A1:Q55 stops before rows 56–57 (BG) [F] |
| SIR Reference | A1:I86 | 85 | 9 | 34 (all in A) | Column I has **no header** [F]; filter A1:I84 |
| Export | A1:R1 | 0 | 18 | 0 | Header only; filter A1:L12 over empty rows [F] |
| Technical SIR | A1:D985 | 984 | 4 | 0 | |
| Technical SIRG | A1:H1005 | 1 004 | 8 | 0 | |
| Other Logic | A1:A6 | 5 | 1 | 0 | |
| Validation | A1:F34 | 33 (longest list) | 6 | 0 | 6 independent lists |
| Sheet2 | A1:A12 | 12 | 1 | 0 | **No header**: row 1 is data (`ES`) [F] |
| Sheet1 | A1:H1 | 1 | 8 | 0 | **No header**: one record [F] |

- **[F]** The workbook has **no Excel data-validation rules** and **no defined names**. The Validation tab is a reference list that Excel does not enforce.
- **[F]** No merged cells and no Excel tables.

## 2. The three generations of Import rows

The Import sheet is not uniform. Its rows fall into three groups that use the two reference columns differently:

| Rows | Generation | P · Document Reference | Q · SIRG Document Reference | Requirement comes from |
|---|---|---|---|---|
| 2–34 (33 rows) | **Hold-code rules** | Formula `=CONCATENATE(B,"\|Import\|",N,"\|",O)` → `ES\|Import\|DH\|CIDM` | Mostly `TEST\|TEST\|TEST`; 8 rows have `XX\|Import\|PII` | Country / global **hold codes** (N, O) |
| 35–55 (21 rows) | **SIRG rules** | Typed placeholder `TEST\|TEST\|TEST` | Real: `RS\|Import\|PPY`, `DE\|Import\|POA`, … | **SIRG code** in Q |
| 56–57 (2 rows) | **BG** (2026) | Typed `BG\|Import\|POAB` (= Q) | `BG\|Import\|POAB` | SIRG code; P typed as a copy of Q |

All three groups are **[F]**. The interpretation in the last column is **[I]**: it rests on the populated hold codes in rows 2–34 and the populated Q in rows 35–57.

## 3. Import — field-level data dictionary

Abbreviations: **Kind:**
- BI = business input
- REF = reference / lookup value
- DER = derived
- UNR = unresolved

**Req.:** required / optional / conditional, each only where the evidence supports it; otherwise TBC.

| Col | Header (exact) | Meaning | Kind | Possible source | Req. | Observed data | Type / normalisation | Validation and risks |
|---|---|---|---|---|---|---|---|---|
| A | `Region` | Region of the country [I] | BI (REF-checkable) | Validation.Region | TBC (filled 56/56) | EU, ME, SB, AM | text | **AM** (6 MX rows) is not in Validation.Region [F] |
| B | `Country` | Destination country, ISO-2 [I] | BI | Validation.Country, Technical SIRG `DHL Ctry Cd` | TBC (56/56) | 21 countries | text, upper | RS, MX, ID not in Validation.Country [F]; Validation has `SK ` with a trailing space [F] |
| C | `B2B/B2C` | Shipment classification | BI | Validation.B2B/B2C | TBC (56/56) | B2C, C2C, B2B | text | **C2C** (6 rows) is not in the Validation list (B2B, B2C, B2B/B2C) [F] |
| D | `Effective Date (DD-MM-YYY)` | Start of validity | BI | approved business input only | TBC (56/56) | 6 values, e.g. `01-01-2021`, `24-09-2026` | **Stored as text** DD-MM-YYYY [F]; normalised to an ISO date kept alongside | Header says `YYY` (typo) [F] |
| E | `Date of Expiry (DD-MM-YYY)` | End of validity | BI | business input | optional? (35/56 filled) | only one value: `02-01-2021` | text → date | `02-01-2021` is before the effective date on rows 25, 52, 54 [F]; on rows 2–34 it is one day after the effective date (Q-05) |
| F | `Network Product Code` | Product codes the rule applies to | BI | — | TBC (56/56) | always `H,V,Y,M,E,P,8,J,3` | comma list | Single value everywhere; no catalog in the workbook [F] |
| G | `Declared Value/ Intristic Value` | Value basis for thresholds | BI | Validation list | TBC (56/56) | DV, IV | text | Filled even where no threshold exists (e.g. rows 38, 48) [F] |
| H | `Currency` | Currency of the thresholds | BI | Validation.Currency List | TBC (56/56) | 8 currencies | ISO-4217 text | AED, BGN, QAR not in Validation.Currency List [F] |
| I | `Min Value (>=)` | Inclusive lower value bound | BI | — | optional (48/56) | 150, 0, 1000, 50.01 … | number | Inclusive by header; strict bounds written as `x.01` (50.01, 150.01) [I] |
| J | `Max Value (<=)` | Inclusive upper value bound | BI | — | optional (10/56) | 999.99, 1499 | number | — |
| K | `Shipt Weight (kg) (>=)` | Inclusive lower weight bound | BI | — | optional (5/56) | 0, 4.99 | number | — |
| L | `Shipt Weight (kg) (<=)` | Inclusive upper weight bound | BI | — | optional (3/56) | 29.9 | number | — |
| M | `Other Logic` | Extra condition expression | BI (REF: Other Logic tab) | Other Logic palette | optional (13/56) | 9 distinct | text, **never executed** | Palette entry 1 uses `,` inside `matchCiMask` where Import uses `\|` [F] |
| N | `Country Hold Code` | Country-specific hold code | BI | — | conditional (26/56; rows 2–34 only) | 18 codes incl. `TBD`, `NCI/POA`, numbers 1 and 3 | text (numbers kept as text) | `TBD` placeholder (rows 32–33); composite `NCI/POA` (row 31) [F] |
| O | `Global Hold Code` | Global hold code | BI | — | conditional (33/56; rows 2–34 only) | CIDM, CPA, VALU, CNPK | text | — |
| P | `Document Reference` | Key linking the rule to its **SIR Reference** lines | DER (formula) / typed | `Country\|Import\|N\|O` | TBC (56/56) | 33 formulas; 23 typed (21 × `TEST\|TEST\|TEST`, 2 BG) | text | Placeholder on rows 35–55 [F]; see §5 |
| Q | `SIRG Document Reference` | Key of the requirement **group** for the country | REF | `Country\|Import\|SIRG Cd` → Technical SIRG | TBC (56/56) | 25 distinct; 24 placeholders | text | **Every non-placeholder Q resolves** to exactly one Technical SIRG row [F] |

## 4. SIR Reference — columns

| Col | Header | Observed | Notes |
|---|---|---|---|
| A | Document Reference | 34 formulas `=IF(Import!P<n><>0,Import!P<n>,"")`; 51 typed | Legacy join to Import P. **Formula positions are load-bearing** [F]: inserting an Import row re-points them. Cached values match today's Import P on every formula row [F] |
| B | SIR Document Reference | `Country\|Import\|SIRGCd\|CmptNm` or `TEST\|TEST\|TEST\|TEST` | New-style join: its first three parts equal Import Q [F] |
| C | Waived if Whitelisted | `Y` ×20, blank | Y/N flag [I] |
| D | Waived to Validate | `Y` ×3, **`4`** ×1 (row 82), blank | `4` is not Y/N (Q-06) |
| E | Check if Service Code= | `PQ` ×34, blank | |
| F | CmptNm | 28 distinct | Not unique (see §6) |
| G | SIR Technical Id | GUID, 48 filled | Every filled id exists in Technical SIR with the same CmptNm [F] |
| H | AttributeID | GUIDs joined by `&&` (some `&`), 46 filled | One SIR Reference row = one or more attributes |
| I | *(no header)* | 49 filled | **[I] Human-readable attribute labels**: the entry count equals the AttributeID count in every sampled row, and the labels are short forms of the package's attribute names (`NID` ↔ *National ID Number*, `DOB` ↔ *Date Of Birth*). Stored as `col_09_unheaded` (Q-01) |

## 5. Document Reference vs SIRG Document Reference — not the same thing

- **`SIRG Document Reference` (Q)** names a **requirement group for a country**: `Country|Import|SIRGCd`, e.g. `DE|Import|POA`. It resolves through **Technical SIRG**, keyed on country + processing type + SIRG code, to one group, one component and one SIR technical ID.
- **`Document Reference` (P)** is the rule's key into **SIR Reference**, the attribute-level lines that say *which* attributes are asked, plus waivers and the service-code check. In hold-code rules it is `Country|Import|CountryHold|GlobalHold`. It is a different key space: `ES|Import|DH|CIDM` is about hold codes, not a SIRG.
- **[F]** For BG (rows 56–57) both columns hold the same typed value. That is the only place they coincide, so it is not evidence that they are interchangeable (Q-02).
- **[F]** Linking is done in **two ways**:

  | Style | SIR Reference rows | Join |
  |---|---|---|
  | Legacy | 2–61 | `SIR Reference.A = Import.P` |
  | New | 62–86 | `SIR Reference.A = TEST|TEST|TEST|TEST` and `left(SIR Reference.B, 3 parts) = Import.Q` |

  The **BG rows (85–86) fill both A and B**.

### Row-level traces

| Trace | Import | → Technical SIRG | → Technical SIR | → SIR Reference |
|---|---|---|---|---|
| **DE · POA** | row 38: Q `DE\|Import\|POA`, P `TEST\|TEST\|TEST`, Other Logic `incotermCodeList.contains("DDP")` | row 613: DE · IMP_CLR · POA → CmptNm **DEPOA**, SIR `b5a141ed…` [F] | `b5a141ed…` = DEPOA [F] | row 84: B `DE\|Import\|POA\|DEPOA`, G `b5a141ed…`, label *Power of Attorney*, Waived if Whitelisted Y [F] |
| **BG · POAB** | row 56: P = Q = `BG\|Import\|POAB`, `serviceCodeList.contains("DD")` | BG · IMP_CLR · POAB → **POABBG**, SIR `7053ef19…` [F] | `7053ef19…` = POABBG [F] | row 85: A `BG\|Import\|POAB`, B `BG\|Import\|POAB\|POABBG`, **no AttributeID** (the whole definition) [F] |
| **BG · IOSS** | row 57: `!serviceCodeList.contains("DD")` | BG · IMP_CLR · IOSS → **IOSSBG**, SIR `af262af3…` [F] | `af262af3…` = IOSSBG [F] | row 86 [F] |
| **MX · IRID** (1 → many) | rows 41 (B2C), 44 (C2C): Q `MX\|Import\|IRID` | → IRIDMX `bd0fdd5f…` | ✓ | **4 rows** (67–70), one per attribute: TAX ID, CURP, Foreigner TAX ID, Foreigner National ID [F] |
| **ES hold-code** | row 2: P (formula) `ES\|Import\|DH\|CIDM`, Q `TEST…` | — (no SIRG) | — | rows 2–4 (A = formula/typed), CmptNm *Identification*, no SIR id [F] |
| **NO hold-code** | row 4: P `NO\|Import\|PFX\|CIDM`, Q `NO\|Import\|PII` | NO · PII → resolves [F] | ✓ | rows 6–7: SIR id `f57a161a…`, 1 and 3 attributes [F] |

**[F] The relationship is one-to-many.** One Import rule has 0..n SIR Reference lines. MX IRID has 4; BG has 1 with no attributes; RS PPY has 1.

## 6. Technical SIR and Technical SIRG

- **Technical SIR:** 984 rows.
  - `SIR Technical ID` is unique and the natural key [F].
  - **CmptNm is not unique**: 44 names repeat, e.g. `PPYComposed` ×31 and `Identification` ×22, each with different IDs [F]. No uniqueness may be put on CmptNm.
  - 21 rows have an empty `Dsc` [F].
- **Technical SIRG:** 1 004 rows.
  - 94 SIRG IDs, 96 countries, processing type always `IMP_CLR` [F].
  - **`SIRG Dsc` is empty on all 1 004 rows** [F]. It is kept, not dropped.
  - **Key (`DHL Ctry Cd`, `Processing Type`, `SIRG Cd`) is unique except for one exact duplicate**: rows 877 and 880, AU · GSTE, identical in every column [F]. That makes it a duplicate *record*, not a second mapping; it is kept and reported.
  - Every `SIR Technical ID` exists in Technical SIR with the same CmptNm [F].
- Repeated component identifiers across SIRG rows are **valid mappings**, the same component reused by several countries or groups, not duplicates [F].

## 7. Other sheets

- **Sheet1** — one record shaped like a Technical SIRG row: `dfb77196… · POA · Power of Attorney · (blank) · DE · IMP_CLR · DEPOA · 1595f691…`.
  - It has the same key as Technical SIRG row 613 but a **different SIR Technical ID** (`1595f691…` vs `b5a141ed…`), and `1595f691…` is not in Technical SIR [F].
  - [I] An older or alternative DE POA mapping. Stored as a source record with the inferred SIRG schema (Q-07).
- **Sheet2** — 12 ISO codes without a header: ES NO FI GR RO CZ ZA LB QA BH TR ID.
  - [F] These are 12 of the 15 countries of the hold-code Import rows (missing HU, IL, SK).
  - [F] ID is not in Validation.Country.
  - Purpose unknown (Q-08).
- **Validation** — six independent lists (Region, B2B/B2C, value basis, currency, Waived if Whitelisted, Country).
  - Not enforced by Excel [F].
  - They do not cover what Import uses: AM, C2C, RS, MX, ID, AED, BGN, QAR [F].
  - `SK ` has a trailing space [F].
  - Its country list (33) and Sheet2 (12) differ, so both are kept with their origin and not merged.
- **Other Logic** — 5 expressions, kept as inert text.
  - Only `!serviceCodeList.contains("DD")` is used verbatim in Import [F].
  - Entry 1 uses `shortCode,==,SDT` where Import uses `shortCode|==|SDT` [F], and it has trailing spaces [F].
- **Export** — header row only, 18 columns: Import's 17 plus **`Business Owner`** [F].
  - [I] An output template; its purpose is not confirmed (Q-09).

## 8. Reconciliation highlights (all rows: `generated/reconciliation.md`)

| Finding | Rows |
|---|---|
| Expiry before effective date | Import 25, 52, 54 |
| Document Reference placeholder `TEST` | Import 35–55 |
| SIRG Document Reference placeholder `TEST` | 24 Import rows (2–34 range) |
| Hold code placeholder `TBD` | Import 32, 33 · composite `NCI/POA` row 31 |
| Business conditions but both references placeholders | Import 32, 33 |
| Value not in Validation lists | 30 cells (AM ×6, MX ×6, C2C ×6, RS ×5, AED ×3, BGN ×2, ID, QAR) |
| SIR Reference line with no matching Import rule | SIR Reference 33, 52–56, 59, 60 (NO, LB, DK, BH) |
| `Waived to Validate` = `4` | SIR Reference 82 |
| Exact duplicate SIRG row | Technical SIRG 880 (= 877) |
| Sheet1 differs from its SIRG row | Sheet1 row 1 vs Technical SIRG 613 |
| Rows outside the Import filter range | Import 56, 57 |
| Dates stored as text | all 91 date cells |

## 9. Open questions

| # | Question | Evidence |
|---|---|---|
| Q-01 | Is SIR Reference column I the attribute **label** list, positionally aligned with AttributeID? | Counts match per row; labels are short forms of package attribute names (rows 6–11, 24–27) |
| Q-02 | Should BG's Document Reference be the SIRG reference (rows 56–57), or follow a convention? Which convention applies to SIRG rules? | Rows 35–55 use a `TEST` placeholder; BG copies Q |
| Q-03 | Does `Import` in a reference always mean processing type `IMP_CLR`? | Technical SIRG has only IMP_CLR; references always say `Import` |
| Q-04 | Are hold-code rules (rows 2–34) still live, and is their SIRG reference meant to stay `TEST`? | 24 of 33 have a `TEST` Q |
| Q-05 | What does expiry `02-01-2021` mean on rows 2–34 (one day after effective), and on 25/52/54 (before effective)? | Same value on all 35 filled expiry cells |
| Q-06 | What does `4` in *Waived to Validate* mean (SIR Reference 82)? | Only non-Y value |
| Q-07 | Is Sheet1 an older DE POA mapping that should be retired? | SIR id differs from Technical SIRG 613 and is not in Technical SIR |
| Q-08 | What is Sheet2's country list for? | 12 of the 15 hold-code countries |
| Q-09 | Is Export the target for an export direction, and is `Business Owner` required there? | Header only |
| Q-10 | Should the Validation lists be extended (AM, C2C, AED, BGN, QAR, RS, MX, ID) or are those Import values wrong? | 30 cells outside the lists |
| Q-11 | Are the 8 orphan SIR Reference lines (NO, LB, DK, BH) obsolete or waiting for Import rules? | No Import P equals their A |
| Q-12 | Should `Network Product Code` ever differ from `H,V,Y,M,E,P,8,J,3`? Is there a product catalog? | One value on all 56 rows |
| Q-13 | AU · GSTE duplicate in Technical SIRG (877/880): drop one in the source, or keep both? | Identical records |
