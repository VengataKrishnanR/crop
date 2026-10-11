# CCRE Onboarding v3 — Quick Start

## 1. Start

Double-click **`START.bat`** and open **http://localhost:8000**. To start by hand instead, see README → How to run.

Sign in as **`admin@ccre.local` / `ChangeMe123!`**, click **Password** and change it.

## 2. Add users (Admin)

| Add | Role | Countries |
|---|---|---|
| Your PM | PM | — |
| A CCRE consultant | CCRE_CONSULTANT | — |
| A CCRE team member | CCRE_TEAM | — |
| A country business user | BUSINESS | e.g. `DE` |

Use a private browser window for each person to sign in side by side.

Optional: Admin → **Email** — enter your SMTP server (without one, emails land in `.ccre_data\outbox\` and are listed under *Sent emails*).

Then, still as admin, scroll to **UAT execution endpoints**: preset *CRMS categorization rule engine*, name `CRMS TEST`, the URL, `x-api-key` and the key → **Save endpoint** → **Test**. Add `CRMS UAT` the same way if you want environment comparison.

## 3. Walk one onboarding (DE works fully offline)

| # | Who | Where | Do |
|---|---|---|---|
| 1 | Business | Onboardings → **+ New** | Country `DE`, title *POA for DDP shipments* |
| 2 | Business | 1. Requirement → **Form + NLP** (or **Chat**) | *DE consumer shipments must provide a Power of Attorney when the incoterm is DDP*, codes `POA` → **Convert with NLP** → **Submit requirement for review** |
| 3 | CCRE consultant | Action bar | **Approve requirement** |
| 4 | PM | 2. Timeline | Answer the questionnaire → **Generate timeline** → **Submit timeline** → **Approve and publish timeline** |
| 5 | Business | 2. Timeline | Sees the approved plan |
| 6 | CCRE team | 3. Rule config + DMG | **Start M2C draft** (copies DE's workbook row) → optionally **Convert requirement to M2C (AI)** and accept or reject the proposal |
| 6a | CCRE team | 3. → *DMG email template and recipients* | Paste your DMG template (use the `{{placeholders}}` shown), set **To / Cc** → **Save template** (once) |
| 6b | CCRE team | 3. → DMG email | **Prepare DMG email from template** → check / edit → **Submit for CCRE review** |
| 6c | CCRE consultant | 3. → DMG email | **Approve and send** (or **Reject** with the reason) → “Task completed” |
| 6d | CCRE team | Action bar | **Submit rule config + DMG for sanity check** |
| 7 | CCRE team | 4. Sanity check | Read the checklist (all ✓) → **Approve sanity check** |
| 8 | CCRE team | 5. UAT test case prep | **Generate test cases (AI)** and/or **+ Add scenario** → **Submit test cases for CCRE approval** |
| 9 | CCRE consultant | 6. Review | **Approve / Reject** each row (or **Approve all waiting**) → **Approve test cases (send to business)** |
| 10 | Business | 6. Test case review | Optional **+ Add scenario**; **Approve / Reject** each row → **Approve test cases (start UAT)** |
| 11 | CCRE team | 7. UAT execution | Upload sample payloads if needed (e.g. your `TCxxx.json`) → choose **Run against** (and optionally **Compare with**) and the sample → **Run UAT**. Results move to CCRE review automatically |
| 12 | CCRE team | 8. Review | Download the **Request / Response** per test or **Download all (zip)**; on failure **Analyse failure (AI)** → **Failures found — correct the M2C** (back to step 6), else **CCRE accepts results** |
| 13 | Business | 7. Sign-off | **Business signs off UAT** |
| 14 | CCRE team | 9. RTP | **Build export bundle** → Support uploads → **Confirm production upload** |

Then open **KPIs**.

> Anyone who is **not** the approver at a step sees “Waiting for …” and **Send reminder email** — try it as the business user while the requirement is with the CCRE consultant.

> BG is a good negative demo: its IOSS/POAB definitions and country mapping are missing from config package 2.10.4-beta.2, so step 7 stays blocked until Support rebuilds the package.

## Essential commands

| Task | Command (venv active) |
|---|---|
| Start | `uvicorn server.app:app --port 8000` |
| Reload the reference data | stop the server, delete `.ccre_data\ccre_v2.db`, run `ccre bootstrap` |
| Run tests + XLSX report | `pytest` |
| Check an expression | `ccre expr "!serviceCodeList.contains(\"DD\")"` |
