# Workbook profile and reconciliation (generated)

- File: `M2c_6_5_ver_1_W29_2.10.9-beta.2_20262608-131409_20262409-100918_20262409-144825_20262409-162826 (2).xlsx`
- SHA-256: `8a8ad95e442795d69dad1b558249c77e042be5308fcfa672ce43dfdded04f393`
- Size: 130750 bytes

## Inventory

| Sheet | Used range | Data rows | Columns | Formula cells | Header row | Filter |
|---|---|---|---|---|---|---|
| Import | A1:Q57 | 56 | 17 | 33 | row 1 | A1:Q55 |
| SIR Reference | A1:I86 | 85 | 9 | 34 | row 1 | A1:I84 |
| Export | A1:R1 | 0 | 18 | 0 | row 1 | A1:L12 |
| Technical SIR | A1:D985 | 984 | 4 | 0 | row 1 | A1:D985 |
| Technical SIRG | A1:H1005 | 1004 | 8 | 0 | row 1 | A1:H1005 |
| Other Logic | A1:A6 | 5 | 1 | 0 | row 1 | — |
| Validation | A1:F34 | 33 | 6 | 0 | row 1 | — |
| Sheet2 | A1:A12 | 12 | 1 | 0 | none (data starts row 1) | — |
| Sheet1 | A1:H1 | 1 | 8 | 0 | none (data starts row 1) | — |

## Columns

### Import

| Col | Header | Filled | Empty | Formulas | Types | Distinct | Top values |
|---|---|---|---|---|---|---|---|
| A | Region | 56 | 0 | 0 | {'str': 56} | 4 | `EU` ×37; `ME` ×10; `AM` ×6 |
| B | Country | 56 | 0 | 0 | {'str': 56} | 21 | `MX` ×6; `BH` ×5; `RS` ×5 |
| C | B2B/B2C | 56 | 0 | 0 | {'str': 56} | 3 | `B2C` ×49; `C2C` ×6; `B2B` ×1 |
| D | Effective Date (DD-MM-YYY) | 56 | 0 | 0 | {'str': 56} | 6 | `01-01-2021` ×33; `29-12-2024` ×8; `01-06-2024` ×6 |
| E | Date of Expiry (DD-MM-YYY) | 35 | 21 | 0 | {'str': 35} | 1 | `02-01-2021` ×35 |
| F | Network Product Code | 56 | 0 | 0 | {'str': 56} | 1 | `H,V,Y,M,E,P,8,J,3` ×56 |
| G | Declared Value/ Intristic Value | 56 | 0 | 0 | {'str': 56} | 2 | `DV` ×44; `IV` ×12 |
| H | Currency | 56 | 0 | 0 | {'str': 56} | 8 | `EUR` ×30; `USD` ×9; `BHD` ×5 |
| I | Min Value (>=) | 48 | 8 | 0 | {'int': 42, 'float': 6} | 10 | `150` ×16; `0` ×9; `1000` ×5 |
| J | Max Value (<=) | 10 | 46 | 0 | {'int': 3, 'float': 7} | 2 | `999.99` ×7; `1499` ×3 |
| K | Shipt Weight (kg) (>=) | 5 | 51 | 0 | {'int': 3, 'float': 2} | 2 | `0` ×3; `4.99` ×2 |
| L | Shipt Weight (kg) (<=) | 3 | 53 | 0 | {'float': 3} | 1 | `29.9` ×3 |
| M | Other Logic | 13 | 43 | 0 | {'str': 13} | 9 | `!serviceCodeList.contains("DD")` ×4; `serviceCodeList.contains("DD")` ×2; `matchCiMask("shortCode|==|SDT","value|==` ×1 |
| N | Country Hold Code | 26 | 30 | 0 | {'str': 24, 'int': 2} | 18 | `POA` ×3; `CNPK` ×3; `NCI` ×3 |
| O | Global Hold Code | 33 | 23 | 0 | {'str': 33} | 4 | `CIDM` ×14; `CPA` ×11; `VALU` ×7 |
| P | Document Reference | 56 | 0 | 33 | {'str': 56} | 36 | `TEST|TEST|TEST` ×21; `ES|Import|DH|CIDM` ×1; `ES|Import|CM|CPA` ×1 |
| Q | SIRG Document Reference | 56 | 0 | 0 | {'str': 56} | 25 | `TEST|TEST|TEST` ×24; `BH|Import|PII` ×3; `ZA|Import|PII` ×2 |

### SIR Reference

| Col | Header | Filled | Empty | Formulas | Types | Distinct | Top values |
|---|---|---|---|---|---|---|---|
| A | Document Reference | 85 | 0 | 34 | {'str': 85} | 44 | `TEST|TEST|TEST|TEST` ×23; `ZA|Import|NCI|CIDM` ×4; `LB|Import|FRML|CIDM` ×4 |
| B | SIR Document Reference | 85 | 0 | 0 | {'str': 85} | 19 | `TEST|TEST|TEST|TEST` ×57; `MX|Import|IRID|IRIDMX` ×4; `ID|Import|PII|Identification` ×3 |
| C | Waived if Whitelisted | 20 | 65 | 0 | {'str': 20} | 1 | `Y` ×20 |
| D | Waived to Validate | 4 | 81 | 0 | {'str': 3, 'int': 1} | 2 | `Y` ×3; `4` ×1 |
| E | Check if Service Code= | 34 | 51 | 0 | {'str': 34} | 1 | `PQ` ×34 |
| F | CmptNm | 85 | 0 | 0 | {'str': 85} | 28 | `Identification` ×24; `POA` ×12; `PPY` ×11 |
| G | SIR Technical Id | 48 | 37 | 0 | {'str': 48} | 25 | `917cb7dc-3e25-4420-b07e-74d5322225ed` ×4; `e4fd168a-e13a-43bc-a6d8-92a3030dea94` ×4; `81d8263e-5562-4f40-b3c6-b8d2365fac8e` ×4 |
| H | AttributeID | 46 | 39 | 0 | {'str': 46} | 44 | `8ef75c9c-3b58-432e-ad2e-0a3d7fe5f066&&ce` ×2; `2d578111-ca23-4d22-8c03-d0420819ec0c&&52` ×2; `60fd6f23-847f-4eab-a880-2ed1c8ef0244` ×1 |
| I | *(no header)* | 49 | 36 | 0 | {'str': 49} | 41 | `Passport Number && Passport Image` ×3; `National ID` ×2; `NID` ×2 |

### Export

| Col | Header | Filled | Empty | Formulas | Types | Distinct | Top values |
|---|---|---|---|---|---|---|---|
| A | Region | 0 | 0 | 0 | {} | 0 |  |
| B | Country | 0 | 0 | 0 | {} | 0 |  |
| C | B2B/B2C | 0 | 0 | 0 | {} | 0 |  |
| D | Effective Date (DD-MM-YYY) | 0 | 0 | 0 | {} | 0 |  |
| E | Date of Expiry (DD-MM-YYY) | 0 | 0 | 0 | {} | 0 |  |
| F | Network Product Code | 0 | 0 | 0 | {} | 0 |  |
| G | Declared Value/ Intristic Value | 0 | 0 | 0 | {} | 0 |  |
| H | Currency | 0 | 0 | 0 | {} | 0 |  |
| I | Min Value (>=) | 0 | 0 | 0 | {} | 0 |  |
| J | Max Value (<=) | 0 | 0 | 0 | {} | 0 |  |
| K | Shipt Weight (kg) (>=) | 0 | 0 | 0 | {} | 0 |  |
| L | Shipt Weight (kg) (<=) | 0 | 0 | 0 | {} | 0 |  |
| M | Other Logic | 0 | 0 | 0 | {} | 0 |  |
| N | Country Hold Code | 0 | 0 | 0 | {} | 0 |  |
| O | Global Hold Code | 0 | 0 | 0 | {} | 0 |  |
| P | Document Reference | 0 | 0 | 0 | {} | 0 |  |
| Q | SIRG Document Reference | 0 | 0 | 0 | {} | 0 |  |
| R | Business Owner | 0 | 0 | 0 | {} | 0 |  |

### Technical SIR

| Col | Header | Filled | Empty | Formulas | Types | Distinct | Top values |
|---|---|---|---|---|---|---|---|
| A | CmptNm | 984 | 0 | 0 | {'str': 984} | 725 | `PPYComposed` ×31; `Identification` ×22; `CommInv` ×21 |
| B | Nm | 984 | 0 | 0 | {'str': 984} | 980 | `Alcohol Shipment Requirements - US` ×3; `Power of Attorney - DE` ×2; `Power of Attorney - BG` ×2 |
| C | Dsc | 963 | 21 | 0 | {'str': 963} | 427 | `Proof of Payment` ×41; `Power of Attorney - Composed` ×23; `Personal Identification for the user` ×22 |
| D | SIR Technical ID | 984 | 0 | 0 | {'str': 984} | 984 | `1900c4f0-92e5-4790-bb71-9334873966a1` ×1; `d3156d07-c521-426b-83ed-ae41458f8d52` ×1; `e3e59bb6-df16-4c72-abb0-58fec0fab955` ×1 |

### Technical SIRG

| Col | Header | Filled | Empty | Formulas | Types | Distinct | Top values |
|---|---|---|---|---|---|---|---|
| A | SIRG Technical ID | 1004 | 0 | 0 | {'str': 1004} | 94 | `ab097089-4df4-458e-ad53-a83553f51b67` ×70; `946b08d6-f18d-4cb6-a5f1-4888f1a5b646` ×59; `e4ab8623-c01b-4310-b3b1-d6550e6b6da6` ×57 |
| B | SIRG Cd | 1004 | 0 | 0 | {'str': 1004} | 94 | `CPPY` ×70; `PII` ×59; `INV` ×57 |
| C | SIRG Nm | 1004 | 0 | 0 | {'str': 1004} | 86 | `Proof of Payment Document - Consignee` ×70; `Consignee ID required` ×59; `Commercial Invoice is required` ×57 |
| D | SIRG Dsc | 0 | 1004 | 0 | {} | 0 |  |
| E | DHL Ctry Cd | 1004 | 0 | 0 | {'str': 1004} | 96 | `US` ×34; `CA` ×28; `IL` ×27 |
| F | Processing Type | 1004 | 0 | 0 | {'str': 1004} | 1 | `IMP_CLR` ×1004 |
| G | CmptNm | 1004 | 0 | 0 | {'str': 1004} | 725 | `PPYComposed` ×31; `Identification` ×22; `CommInv` ×21 |
| H | SIR Technical ID | 1004 | 0 | 0 | {'str': 1004} | 984 | `7d37e969-12b0-4b80-a815-0b30f45ad46c` ×3; `e858f010-24e4-40fe-959d-f58c134e66b2` ×3; `fa288a13-6fcd-43e8-bcef-8b71c39dff99` ×3 |

### Other Logic

| Col | Header | Filled | Empty | Formulas | Types | Distinct | Top values |
|---|---|---|---|---|---|---|---|
| A | Other Logic | 5 | 0 | 0 | {'str': 5} | 5 | `(matchCiMask("shortCode,==,SDT") && matc` ×1; `OriginCountry=="AU"||OriginCountry=="BD"` ×1; `OriginCountry!="UK" && !serviceCodeList.` ×1 |

### Validation

| Col | Header | Filled | Empty | Formulas | Types | Distinct | Top values |
|---|---|---|---|---|---|---|---|
| A | Region | 3 | 30 | 0 | {'str': 3} | 3 | `EU` ×1; `ME` ×1; `SB` ×1 |
| B | B2B/B2C | 3 | 30 | 0 | {'str': 3} | 3 | `B2B` ×1; `B2C` ×1; `B2B/B2C` ×1 |
| C | Declared Value/ Intristic Value | 2 | 31 | 0 | {'str': 2} | 2 | `DV` ×1; `IV` ×1 |
| D | Currency List | 7 | 26 | 0 | {'str': 7} | 7 | `EUR` ×1; `SEK` ×1; `USD` ×1 |
| E | Waived if Whitelisted | 2 | 31 | 0 | {'str': 2} | 2 | `Y` ×1; `N` ×1 |
| F | Country | 33 | 0 | 0 | {'str': 33} | 33 | `IT` ×1; `ES` ×1; `IC` ×1 |

### Sheet2

| Col | Header | Filled | Empty | Formulas | Types | Distinct | Top values |
|---|---|---|---|---|---|---|---|
| A | *(no header)* | 12 | 0 | 0 | {'str': 12} | 12 | `ES` ×1; `NO` ×1; `FI` ×1 |

### Sheet1

| Col | Header | Filled | Empty | Formulas | Types | Distinct | Top values |
|---|---|---|---|---|---|---|---|
| A | *(no header)* | 1 | 0 | 0 | {'str': 1} | 1 | `dfb77196-12f7-434c-9cab-deee448ad983` ×1 |
| B | *(no header)* | 1 | 0 | 0 | {'str': 1} | 1 | `POA` ×1 |
| C | *(no header)* | 1 | 0 | 0 | {'str': 1} | 1 | `Power of Attorney` ×1 |
| D | *(no header)* | 0 | 1 | 0 | {} | 0 |  |
| E | *(no header)* | 1 | 0 | 0 | {'str': 1} | 1 | `DE` ×1 |
| F | *(no header)* | 1 | 0 | 0 | {'str': 1} | 1 | `IMP_CLR` ×1 |
| G | *(no header)* | 1 | 0 | 0 | {'str': 1} | 1 | `DEPOA` ×1 |
| H | *(no header)* | 1 | 0 | 0 | {'str': 1} | 1 | `1595f691-8d36-40db-a273-fb8f233c9872` ×1 |

## Findings by code

| Code | Count |
|---|---|
| EXPORT_HEADER_ONLY | 1 |
| IMP_BUSINESS_WITHOUT_REFERENCE | 2 |
| IMP_DATE_TEXT | 91 |
| IMP_DOCREF_FORMULA | 33 |
| IMP_DOCREF_LITERAL | 23 |
| IMP_DOCREF_PLACEHOLDER | 23 |
| IMP_EXPIRY_BEFORE_EFFECTIVE | 3 |
| IMP_HOLD_COMPOSITE | 1 |
| IMP_HOLD_PLACEHOLDER | 2 |
| IMP_NOT_IN_VALIDATION_LIST | 30 |
| IMP_OUTSIDE_AUTOFILTER | 2 |
| IMP_SIRGREF_PLACEHOLDER | 24 |
| OTHERLOGIC_ENTRY | 5 |
| SHEET1_DIFFERS_FROM_SIRG | 1 |
| SHEET2_COUNTRY_LIST | 1 |
| SREF_DOCREF_ORPHAN | 8 |
| SREF_FLAG_VALUE | 1 |
| SREF_FORMULA_POSITIONAL | 34 |
| SREF_UNHEADED_COLUMN | 1 |
| TSIRG_EXACT_DUPLICATE | 1 |
| TSIR_CMPT_REPEATED | 44 |
| VAL_NOT_ENFORCED | 1 |
| VAL_WHITESPACE | 1 |

## Every finding (row-level reconciliation)

| Severity | Code | Sheet | Row | Column | Value | Finding | Basis |
|---|---|---|---|---|---|---|---|
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 2 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 3 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 5 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 7 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 8 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 9 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 10 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 11 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 12 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 13 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 14 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 15 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 16 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 18 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 21 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 22 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 24 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_EXPIRY_BEFORE_EFFECTIVE | Import | 25 | expiry_date | 02-01-2021 | Expiry 02-01-2021 is before effective 28-02-2022. | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 25 | country | ID | 'ID' is not in the Validation tab list 'Country' (the list is not enforced by Excel). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 26 | currency | QAR | 'QAR' is not in the Validation tab list 'Currency List' (the list is not enforced by Excel). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 27 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 28 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 29 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 30 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_HOLD_COMPOSITE | Import | 31 | country_hold_code | NCI/POA | Hold code holds two codes separated by '/'. | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 31 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_BUSINESS_WITHOUT_REFERENCE | Import | 32 |  |  | Business conditions are filled in but both references are placeholders. | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 32 | document_reference | IL\|Import\|TBD\|CIDM | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_HOLD_PLACEHOLDER | Import | 32 | country_hold_code | TBD | Hold code is a placeholder (TBD). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 32 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_BUSINESS_WITHOUT_REFERENCE | Import | 33 |  |  | Business conditions are filled in but both references are placeholders. | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 33 | document_reference | IL\|Import\|TBD\|CPA | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_HOLD_PLACEHOLDER | Import | 33 | country_hold_code | TBD | Hold code is a placeholder (TBD). | verified |
| warning | IMP_SIRGREF_PLACEHOLDER | Import | 33 | sirg_document_reference | TEST\|TEST\|TEST | SIRG Document Reference is a placeholder (TEST). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 35 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 35 | country | RS | 'RS' is not in the Validation tab list 'Country' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 36 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 36 | country | RS | 'RS' is not in the Validation tab list 'Country' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 37 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 37 | country | RS | 'RS' is not in the Validation tab list 'Country' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 38 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 39 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 39 | country | RS | 'RS' is not in the Validation tab list 'Country' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 40 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 40 | country | RS | 'RS' is not in the Validation tab list 'Country' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 41 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 41 | region | AM | 'AM' is not in the Validation tab list 'Region' (the list is not enforced by Excel). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 41 | country | MX | 'MX' is not in the Validation tab list 'Country' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 42 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 42 | region | AM | 'AM' is not in the Validation tab list 'Region' (the list is not enforced by Excel). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 42 | country | MX | 'MX' is not in the Validation tab list 'Country' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 43 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 43 | region | AM | 'AM' is not in the Validation tab list 'Region' (the list is not enforced by Excel). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 43 | country | MX | 'MX' is not in the Validation tab list 'Country' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 44 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 44 | region | AM | 'AM' is not in the Validation tab list 'Region' (the list is not enforced by Excel). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 44 | shipment_type | C2C | 'C2C' is not in the Validation tab list 'B2B/B2C' (the list is not enforced by Excel). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 44 | country | MX | 'MX' is not in the Validation tab list 'Country' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 45 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 45 | region | AM | 'AM' is not in the Validation tab list 'Region' (the list is not enforced by Excel). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 45 | shipment_type | C2C | 'C2C' is not in the Validation tab list 'B2B/B2C' (the list is not enforced by Excel). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 45 | country | MX | 'MX' is not in the Validation tab list 'Country' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 46 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 46 | region | AM | 'AM' is not in the Validation tab list 'Region' (the list is not enforced by Excel). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 46 | shipment_type | C2C | 'C2C' is not in the Validation tab list 'B2B/B2C' (the list is not enforced by Excel). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 46 | country | MX | 'MX' is not in the Validation tab list 'Country' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 47 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 48 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 49 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 49 | shipment_type | C2C | 'C2C' is not in the Validation tab list 'B2B/B2C' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 50 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 50 | currency | AED | 'AED' is not in the Validation tab list 'Currency List' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 51 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 51 | currency | AED | 'AED' is not in the Validation tab list 'Currency List' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 52 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_EXPIRY_BEFORE_EFFECTIVE | Import | 52 | expiry_date | 02-01-2021 | Expiry 02-01-2021 is before effective 07-01-2026. | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 52 | shipment_type | C2C | 'C2C' is not in the Validation tab list 'B2B/B2C' (the list is not enforced by Excel). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 52 | currency | AED | 'AED' is not in the Validation tab list 'Currency List' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 53 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 54 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_EXPIRY_BEFORE_EFFECTIVE | Import | 54 | expiry_date | 02-01-2021 | Expiry 02-01-2021 is before effective 07-01-2026. | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 54 | shipment_type | C2C | 'C2C' is not in the Validation tab list 'B2B/B2C' (the list is not enforced by Excel). | verified |
| warning | IMP_DOCREF_PLACEHOLDER | Import | 55 | document_reference | TEST\|TEST\|TEST | Document Reference is a placeholder (TEST). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 56 | currency | BGN | 'BGN' is not in the Validation tab list 'Currency List' (the list is not enforced by Excel). | verified |
| warning | IMP_NOT_IN_VALIDATION_LIST | Import | 57 | currency | BGN | 'BGN' is not in the Validation tab list 'Currency List' (the list is not enforced by Excel). | verified |
| warning | SREF_DOCREF_ORPHAN | SIR Reference | 33 | document_reference | BH\|Import\|CNPK\|VALU | No Import row has this Document Reference. | verified |
| warning | SREF_DOCREF_ORPHAN | SIR Reference | 52 | document_reference | NO\|Import\|\|VALU | No Import row has this Document Reference. | verified |
| warning | SREF_DOCREF_ORPHAN | SIR Reference | 53 | document_reference | NO\|Import\|REGD\|ILRQ | No Import row has this Document Reference. | verified |
| warning | SREF_DOCREF_ORPHAN | SIR Reference | 54 | document_reference | NO\|Import\|DEXM\|SHPK | No Import row has this Document Reference. | verified |
| warning | SREF_DOCREF_ORPHAN | SIR Reference | 55 | document_reference | NO\|Import\|\|DIP | No Import row has this Document Reference. | verified |
| warning | SREF_DOCREF_ORPHAN | SIR Reference | 56 | document_reference | NO\|Import\|\|PSVC | No Import row has this Document Reference. | verified |
| warning | SREF_DOCREF_ORPHAN | SIR Reference | 59 | document_reference | LB\|Import\|\|VALU | No Import row has this Document Reference. | verified |
| warning | SREF_DOCREF_ORPHAN | SIR Reference | 60 | document_reference | DK\|Import\|31\|VALU | No Import row has this Document Reference. | verified |
| warning | SREF_FLAG_VALUE | SIR Reference | 82 | waived_to_validate | 4 | '4' is not Y or N. | verified |
| warning | SHEET1_DIFFERS_FROM_SIRG | Sheet1 | 1 |  | POA | Shaped like a Technical SIRG row; same key as row 613 but differs in ['SIR Technical ID']. | inferred |
| warning | TSIRG_EXACT_DUPLICATE | Technical SIRG | 880 |  | GSTE | Identical to row 877. | verified |
| warning | VAL_WHITESPACE | Validation | 18 | Country | SK  | 'SK ' has leading/trailing spaces. | verified |
| info | EXPORT_HEADER_ONLY | Export | 1 |  | A1:R1 | Header row only (18 columns); compared with Import it adds ['Business Owner']. Filter range A1:L12 covers empty rows. | inferred |
| info | IMP_DATE_TEXT | Import | 2 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 2 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 2 | document_reference | ES\|Import\|DH\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 3 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 3 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 3 | document_reference | ES\|Import\|CM\|CPA | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 4 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 4 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 4 | document_reference | NO\|Import\|PFX\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 5 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 5 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 5 | document_reference | FI\|Import\|3\|VALU | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 6 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 6 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 6 | document_reference | FI\|Import\|1\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 7 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 7 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 7 | document_reference | FI\|Import\|\|CPA | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 8 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 8 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 8 | document_reference | GR\|Import\|\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 9 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 9 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 9 | document_reference | GR\|Import\|POA\|CPA | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 10 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 10 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 10 | document_reference | GR\|Import\|CNPK\|VALU | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 11 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 11 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 11 | document_reference | RO\|Import\|N3\|CPA | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 12 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 12 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 12 | document_reference | RO\|Import\|CV\|VALU | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 13 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 13 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 13 | document_reference | RO\|Import\|N2\|CNPK | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 14 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 14 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 14 | document_reference | CZ\|Import\|CIDM\|CPA | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 15 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 15 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 15 | document_reference | CZ\|Import\|CIDM\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 16 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 16 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 16 | document_reference | CZ\|Import\|VALU\|VALU | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 17 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 17 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 17 | document_reference | ZA\|Import\|NCI\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 18 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 18 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 18 | document_reference | ZA\|Import\|INST\|CPA | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 19 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 19 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 19 | document_reference | LB\|Import\|FRML\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 20 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 20 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 20 | document_reference | BH\|Import\|CNPK\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 21 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 21 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 21 | document_reference | BH\|Import\|CNPK\|CPA | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 22 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 22 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 22 | document_reference | TR\|Import\|\|CPA | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 23 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 23 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 23 | document_reference | TR\|Import\|\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 24 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 24 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 24 | document_reference | TR\|Import\|\|VALU | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 25 | effective_date | 28-02-2022 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 25 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 25 | document_reference | ID\|Import\|\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 26 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 26 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 26 | document_reference | QA\|Import\|\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 27 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 27 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 27 | document_reference | HU\|Import\|POA\|CPA | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 28 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 28 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 28 | document_reference | HU\|Import\|NCI\|VALU | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 29 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 29 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 29 | document_reference | SK\|Import\|POA\|CPA | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 30 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 30 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 30 | document_reference | SK\|Import\|NCI\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 31 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 31 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 31 | document_reference | SK\|Import\|NCI/POA\|VALU | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 32 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 32 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 32 | document_reference | IL\|Import\|TBD\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 33 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 33 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 33 | document_reference | IL\|Import\|TBD\|CPA | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 34 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 34 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_FORMULA | Import | 34 | document_reference | ZA\|Import\|EML\|CIDM | Document Reference is the CONCATENATE formula (Country\|Import\|CountryHold\|GlobalHold). | verified |
| info | IMP_DATE_TEXT | Import | 35 | effective_date | 01-06-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 35 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 36 | effective_date | 01-06-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 36 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 37 | effective_date | 01-06-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 37 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 38 | effective_date | 01-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 38 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 39 | effective_date | 01-06-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 39 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 40 | effective_date | 01-06-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 40 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 41 | effective_date | 29-12-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 41 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 42 | effective_date | 29-12-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 42 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 43 | effective_date | 29-12-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 43 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 44 | effective_date | 29-12-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 44 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 45 | effective_date | 29-12-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 45 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 46 | effective_date | 29-12-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 46 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 47 | effective_date | 01-06-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 47 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 48 | effective_date | 29-12-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 48 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 49 | effective_date | 29-12-2024 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 49 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 50 | effective_date | 07-01-2026 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 50 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 51 | effective_date | 07-01-2026 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 51 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 52 | effective_date | 07-01-2026 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 52 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 52 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 53 | effective_date | 07-01-2026 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 53 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 54 | effective_date | 07-01-2026 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DATE_TEXT | Import | 54 | expiry_date | 02-01-2021 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 54 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 55 | effective_date | 07-01-2026 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 55 | document_reference | TEST\|TEST\|TEST | Document Reference is a typed value, not the formula. | verified |
| info | IMP_DATE_TEXT | Import | 56 | effective_date | 24-09-2026 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 56 | document_reference | BG\|Import\|POAB | Document Reference is a typed value, not the formula. | verified |
| info | IMP_OUTSIDE_AUTOFILTER | Import | 56 |  | A1:Q55 | Row is outside the sheet's filter range A1:Q55 (likely appended later). | inferred |
| info | IMP_DATE_TEXT | Import | 57 | effective_date | 24-09-2026 | Date stored as text (DD-MM-YYYY), not as an Excel date; normalised value kept separately. | verified |
| info | IMP_DOCREF_LITERAL | Import | 57 | document_reference | BG\|Import\|IOSS | Document Reference is a typed value, not the formula. | verified |
| info | IMP_OUTSIDE_AUTOFILTER | Import | 57 |  | A1:Q55 | Row is outside the sheet's filter range A1:Q55 (likely appended later). | inferred |
| info | OTHERLOGIC_ENTRY | Other Logic | 2 | A | (matchCiMask("shortCode,==,SDT") && matchCiMask("value,==,<b | Not used verbatim in Import. Has leading/trailing spaces. Uses ',' inside matchCiMask where Import uses '\|'. | verified |
| info | OTHERLOGIC_ENTRY | Other Logic | 3 | A | OriginCountry=="AU"\|\|OriginCountry=="BD"\|\|OriginCountry=="BN | Not used verbatim in Import. | verified |
| info | OTHERLOGIC_ENTRY | Other Logic | 4 | A | OriginCountry!="UK" && !serviceCodeList.contains("DD") | Used verbatim in Import. | verified |
| info | OTHERLOGIC_ENTRY | Other Logic | 5 | A | !serviceCodeList.contains("DD") | Used verbatim in Import. | verified |
| info | OTHERLOGIC_ENTRY | Other Logic | 6 | A | serviceCodeList.contains("DE") \|\| serviceCodeList.contains(" | Not used verbatim in Import. | verified |
| info | SREF_UNHEADED_COLUMN | SIR Reference | 1 | I |  | Column I has no header; its values line up one-to-one with the AttributeID entries and read like attribute names. Stored as col_09_unheaded until confirmed (Q-01). | inferred |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 2 | document_reference | =IF(Import!P2<>0,Import!P2,"") | Links to Import row 2 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 5 | document_reference | =IF(Import!P3<>0,Import!P3,"") | Links to Import row 3 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 6 | document_reference | =IF(Import!P4<>0,Import!P4,"") | Links to Import row 4 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 7 | document_reference | =IF(Import!P4<>0,Import!P4,"") | Links to Import row 4 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 13 | document_reference | =IF(Import!P8<>0,Import!P8,"") | Links to Import row 8 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 16 | document_reference | =IF(Import!P9<>0,Import!P9,"") | Links to Import row 9 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 17 | document_reference | =IF(Import!P10<>0,Import!P10,"") | Links to Import row 10 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 18 | document_reference | =IF(Import!P11<>0,Import!P11,"") | Links to Import row 11 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 19 | document_reference | =IF(Import!P12<>0,Import!P12,"") | Links to Import row 12 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 20 | document_reference | =IF(Import!P13<>0,Import!P13,"") | Links to Import row 13 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 21 | document_reference | =IF(Import!P14<>0,Import!P14,"") | Links to Import row 14 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 22 | document_reference | =IF(Import!P15<>0,Import!P15,"") | Links to Import row 15 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 23 | document_reference | =IF(Import!P16<>0,Import!P16,"") | Links to Import row 16 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 24 | document_reference | =IF(Import!P17<>0,Import!P17,"") | Links to Import row 17 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 28 | document_reference | =IF(Import!P18<>0,Import!P18,"") | Links to Import row 18 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 29 | document_reference | =IF(Import!P19<>0,Import!P19,"") | Links to Import row 19 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 30 | document_reference | =IF(Import!P19<>0,Import!P19,"") | Links to Import row 19 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 31 | document_reference | =IF(Import!P20<>0,Import!P20,"") | Links to Import row 20 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 34 | document_reference | =IF(Import!P21<>0,Import!P21,"") | Links to Import row 21 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 35 | document_reference | =IF(Import!P22<>0,Import!P22,"") | Links to Import row 22 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 36 | document_reference | =IF(Import!P23<>0,Import!P23,"") | Links to Import row 23 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 37 | document_reference | =IF(Import!P23<>0,Import!P23,"") | Links to Import row 23 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 38 | document_reference | =IF(Import!P24<>0,Import!P24,"") | Links to Import row 24 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 39 | document_reference | =IF(Import!P25<>0,Import!P25,"") | Links to Import row 25 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 42 | document_reference | =IF(Import!P26<>0,Import!P26,"") | Links to Import row 26 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 43 | document_reference | =IF(Import!P27<>0,Import!P27,"") | Links to Import row 27 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 44 | document_reference | =IF(Import!P26<>0,Import!P26,"") | Links to Import row 26 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 45 | document_reference | =IF(Import!P27<>0,Import!P27,"") | Links to Import row 27 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 46 | document_reference | =IF(Import!P28<>0,Import!P28,"") | Links to Import row 28 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 47 | document_reference | =IF(Import!P29<>0,Import!P29,"") | Links to Import row 29 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 48 | document_reference | =IF(Import!P30<>0,Import!P30,"") | Links to Import row 30 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 49 | document_reference | =IF(Import!P31<>0,Import!P31,"") | Links to Import row 31 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 50 | document_reference | =IF(Import!P32<>0,Import!P32,"") | Links to Import row 32 by position: inserting or deleting Import rows re-points it. | verified |
| info | SREF_FORMULA_POSITIONAL | SIR Reference | 51 | document_reference | =IF(Import!P33<>0,Import!P33,"") | Links to Import row 33 by position: inserting or deleting Import rows re-points it. | verified |
| info | SHEET2_COUNTRY_LIST | Sheet2 |  | A | ES,NO,FI,GR,RO,CZ,ZA,LB,QA,BH,TR,ID | 12 country codes, no header. Not in Validation.Country: ['ID']. Countries of formula-based Import rows not in Sheet2: ['HU', 'IL', 'SK']. | inferred |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | POAComposed | CmptNm 'POAComposed' appears on 12 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | PPYComposed | CmptNm 'PPYComposed' appears on 31 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | GoodsDesc | CmptNm 'GoodsDesc' appears on 9 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | Identification | CmptNm 'Identification' appears on 22 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | DiplomaticMtr | CmptNm 'DiplomaticMtr' appears on 8 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | GiftShipment | CmptNm 'GiftShipment' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | CooComposed | CmptNm 'CooComposed' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | HealthPermit | CmptNm 'HealthPermit' appears on 13 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | GoodsCertReq | CmptNm 'GoodsCertReq' appears on 10 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | PPY | CmptNm 'PPY' appears on 11 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | VatRedn | CmptNm 'VatRedn' appears on 9 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | CommInv | CmptNm 'CommInv' appears on 21 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | DutyConsent | CmptNm 'DutyConsent' appears on 8 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | HealthPermitFac | CmptNm 'HealthPermitFac' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | ownValDec | CmptNm 'ownValDec' appears on 15 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | CTID | CmptNm 'CTID' appears on 14 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | TmpImport | CmptNm 'TmpImport' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | GoodsLic | CmptNm 'GoodsLic' appears on 13 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | MisInv | CmptNm 'MisInv' appears on 4 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | GoodsType | CmptNm 'GoodsType' appears on 3 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | GoodsDescSngl | CmptNm 'GoodsDescSngl' appears on 11 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | FoodPermit | CmptNm 'FoodPermit' appears on 4 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | ShpDocs | CmptNm 'ShpDocs' appears on 10 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | PrsnlUseConsent | CmptNm 'PrsnlUseConsent' appears on 3 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | DiplomaticExmp | CmptNm 'DiplomaticExmp' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | EImpForm | CmptNm 'EImpForm' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | FoodImports | CmptNm 'FoodImports' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | TradeZone | CmptNm 'TradeZone' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | POA | CmptNm 'POA' appears on 5 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | ResImp | CmptNm 'ResImp' appears on 3 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | EORI | CmptNm 'EORI' appears on 5 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | ConsigneeDtls | CmptNm 'ConsigneeDtls' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | PersonalID | CmptNm 'PersonalID' appears on 11 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | ConsentPOA | CmptNm 'ConsentPOA' appears on 4 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | CITESCertificate | CmptNm 'CITESCertificate' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | TravelProof | CmptNm 'TravelProof' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | BrkrClr | CmptNm 'BrkrClr' appears on 3 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | VhclShp | CmptNm 'VhclShp' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | PymtRcpt | CmptNm 'PymtRcpt' appears on 3 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | MOFAValue | CmptNm 'MOFAValue' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | MedDrugsImp | CmptNm 'MedDrugsImp' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | BTID | CmptNm 'BTID' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | RetExport | CmptNm 'RetExport' appears on 2 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | TSIR_CMPT_REPEATED | Technical SIR |  | CmptNm | INBUS | CmptNm 'INBUS' appears on 6 rows with different SIR Technical IDs — CmptNm is not a key. | verified |
| info | VAL_NOT_ENFORCED | Validation |  |  |  | The workbook has no Excel data-validation rules: the Validation lists are reference only. | verified |
