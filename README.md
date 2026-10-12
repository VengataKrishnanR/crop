# CCRE Rules Intelligence & Onboarding Platform — v3

A Google ADK application that takes a country's customs requirement from the **business team's first message** to **RTP (ready to production)** in CCRE:

- intake by chatbot or by form plus NLP
- a timeline the AI plans from the PM's answers
- the M2C draft and DMG changes, checked by a deterministic validator
- UAT test cases reviewed by the CCRE team and then the business team
- AI-generated payloads executed against the endpoint, with every response reviewed
- a correction loop when tests fail, then business sign-off and RTP

Everything is role-based. **Agents recommend, code validates, humans approve.** No agent can approve anything, move a case, or upload to CCRE.

> Built on the company ADK template (`final_rework`): same layout, the same `components/` LLM gateway (DHL Apigee / stub / OpenAI / Google AI), and the same server, UI and test-report conventions.

---

## How to run

### What you need

- **Windows** with **Python 3.11 or newer** (`python --version`).
- The **reference files** in a folder named `Reference` **next to** this folder:

  ```
  CCRE Rules Intelligence & Support Plaform\
  ├── Reference\                  ← sir-configuration*.zip (or folder) and M2c*.xlsx
  └── ccre-onboarding-agent\      ← this application
  ```

- For real AI answers only: a **DHL Apigee API key** and the **DHL network/VPN**. Without them the app runs in offline mode.

### Option 1 — one click

1. Double-click **`START.bat`** in the `ccre-onboarding-agent` folder.
2. Wait for `Open your browser at: http://localhost:8000`. The first run installs packages and loads `..\Reference`, which takes a few minutes.
3. Open **http://localhost:8000** and sign in as **`admin@ccre.local`** / **`ChangeMe123!`**.
4. Click **Password** to change the admin password, then open **Admin** and add your PM, CCRE consultants, CCRE team and business users.

### Option 2 — step by step (PowerShell)

```powershell
cd "C:\Users\Vengata Krishnan R\OneDrive\Desktop\CCRE Rules Intelligence & Support Plaform\ccre-onboarding-agent"
python -m venv .venv                     # first time only
.\.venv\Scripts\Activate.ps1             # prompt shows (.venv)
pip install -r requirements.txt          # first time only
pip install -e .                         # first time only
python patch_adk.py                      # first time only
copy config\.env.stub .env               # first time only — offline AI, sign-in on
ccre bootstrap                           # first time only — loads ..\Reference
uvicorn server.app:app --port 8000
```

After the first time you only need the `cd`, `Activate.ps1` and `uvicorn` lines (or `START.bat`). If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

### Switch to real AI (DHL GenAI Gateway)

```powershell
copy config\.env.apigee .env
$env:APIGEE_API_KEY = "paste-your-key-here"     # or add APIGEE_API_KEY=... to .env (never share that file)
uvicorn server.app:app --port 8000
```

### Connect UAT to your API (Admin → UAT execution endpoints)

The CRMS API test suite (`TestSuite_CRMS`) is onboarded into the app. Instead of the HTML connector plus a Node proxy, the **admin** enters each target once in the UI:

1. Admin → **UAT execution endpoints** → choose a **preset** (*CRMS categorization rule engine* or *CCRE requirement evaluation*), which fills in the response paths.
2. Enter the **name** (e.g. `CRMS TEST`), **URL**, credential header (`x-api-key`) and **API key**, then click **Save endpoint**. The key is stored encrypted and never shown again; the page shows only `••••last4`.
3. **Test** the endpoint with a sample payload: the page reports reachability, HTTP status and whether the response can be read.

The CCRE team then only picks **Run against** (and optionally **Compare with**, e.g. TEST vs UAT) and clicks **Run UAT**. Sample payloads (e.g. your `TCxxx.json` files) are uploaded on the UAT execution screen. Requests to `*.dhl.com` bypass the corporate proxy, as the suite's proxy did.

Without any endpoint the run uses a built-in **mock CCRE** (offline demo). Your own execution code can still be plugged in as a class; see `tools/execution/custom/README.md`.

---

## What is new in v3

| # | Change | Where |
|---|---|---|
| 1 | **Approve / Reject at every stage.** A reject always asks for the reason, which goes on the record and to the other side. People who are **not** the approver see a banner saying **who the onboarding is waiting for**, plus a **Send reminder email** button. The reminder goes To the approvers with **every user involved in CC** (business users only for their own countries), at most once every 10 minutes. | Action bar and banner on every onboarding |
| 2 | **Sanity check explained.** It is the last gate before UAT preparation. It confirms the M2C rows are valid and that CCRE can actually evaluate them, as a checklist that runs automatically: M2C rows exist · no blocking validation finding · config package covers the country and groups · DMG email task completed. Each item shows ✓/✕ and why. | 4. Sanity check |
| 3 | **DMG email task.** The CCRE team owns the **template and recipients** (Rule config → *DMG email template and recipients*). Per onboarding: **Prepare** fills the template from the onboarding (requirement, M2C rows, requirement definitions and DMG message positions, planned RTP) → edit → **Submit for CCRE review** → a **second** CCRE member **approves and sends** (or rejects with a reason) → the task shows **completed**. A CCRE consultant can mark it **not required** with a reason. Rule config cannot be submitted until the task is completed. | 3. Rule config + DMG |
| 4 | **UAT test cases row by row.** AI-generated rows plus **+ Add scenario**: anyone in CCRE (or the business during their review) describes a scenario in plain words, and it is converted into a test case (NLP). **Every row** gets its own **Approve / Reject** (reason required): first the CCRE team, then the business team. Only rows approved by both are executed. Regenerating AI rows never removes approved rows or scenarios people added. | 5–6. UAT test cases |
| 5 | **Horizontal flow, full width.** The left sidebar is gone. Pick the onboarding from the bar on top, and the flow shows every stage as **Completed / In progress / Not yet started**. | Onboardings |

**Email:** Admin → *Email* sets the SMTP host, port, security, user and password (stored encrypted) and the from-address. **Without an SMTP host, every email is written to `.ccre_data\outbox\` and listed under *Sent emails***, so reminders and DMG emails can be tested and reviewed before SMTP is connected.

---

## Rule configuration workspace

Step 3 is where the M2C is actually built. The draft starts as the country's live rows from the loaded workbook, and every edit is checked immediately.

| Sub-tab | What it does |
|---|---|
| **Rules (Import + SIR Reference)** | One line per Import row with a status: ✓ OK · ! to check · ⚠ package gap · ✕ error. **Edit** opens the row: every Import column (lists come from the workbook's Validation tab), **Other Logic** typed, picked from the workbook palette, or built from choices (service code, incoterm, origin country, short code such as SDT, HS code) and checked by the validator's grammar, plus the row's **requirement definitions**: search the config package, bind, and set *waived to validate* / *waived if whitelisted* / *only if service code* / the attributes. Add, duplicate and remove rows; or let the AI propose rows from the approved requirement and accept them. |
| **Changes vs workbook** | New, changed (field by field: old → new) and removed rows compared with the workbook. |
| **Package coverage** | The Technical SIR / Technical SIRG view: is every group and definition the draft uses shipped by the config package and mapped for the country? Gaps → **Package request (.csv)** for Support, in the package's own mapping format. |
| **DMG email** | The DMG email task (unchanged from v3). |
| **Validate & download** | Full validation, and **Download M2C (.xlsx)**: the country's M2C in the workbook layout (Import, Export, SIR Reference, Technical SIR, Technical SIRG, Other Logic, Validation) plus a Changes tab. Document references are the workbook's `CONCATENATE` formula and SIR Reference positions are generated `IF(Import!P<n>…)` formulas, so they always point at the right row. |

**Errors** (e.g. min value above max, expiry before effective date, unparseable Other Logic, no requirement group) **block "Submit rule config + DMG for sanity check"**. **Package gaps** do not block submitting, because Support fixes them in the package; they are gated at the sanity check. Rows are editable only while the onboarding is in Rule configuration and only by the CCRE team / consultant; every edit is on the audit trail.

**Who submits:** the **business** submits its requirement (the CCRE consultant approves or rejects it); the **CCRE consultant** prepares and submits the timeline (the PM approves or returns it).

---

## Roles (Admin panel)

| Role | Does |
|---|---|
| **ADMIN** | Adds users, assigns roles and (for business users) countries; can read everything |
| **PM** | Answers the timeline questionnaire; approves and publishes the timeline |
| **CCRE_CONSULTANT** | Approves the business requirement; reviews test cases and UAT results |
| **CCRE_TEAM** | Configures the M2C rules and DMG changes, runs the sanity check, prepares and executes UAT, confirms RTP |
| **BUSINESS** | Country business team. Raises onboardings, describes the requirement (chat or form), sees the approved timeline, reviews test cases, signs off UAT. **Sees only their assigned countries and only the business steps**, with no M2C, validation, payloads, KPIs or admin |

`AUTH_MODE=none` (development only) skips sign-in and shows a role switcher in the header.

---

## The lifecycle

```
1  Requirement intake      Business: chatbot or form + NLP, submits   → CCRE consultant approves / rejects
2  Timeline                CCRE consultant plans (AI) and submits     → PM approves (published) / rejects
3  Rule config + DMG       CCRE team: M2C workspace (rows, bindings, changes, coverage, .xlsx); DMG email
4  Sanity check            Checklist: M2C valid · package complete · DMG done → CCRE approves / rejects
5  UAT test case prep      AI rows + "+ scenario" (NLP); may start during step 3
6  UAT test case review    Each row approved/rejected: CCRE team first → then business team
7  UAT execution           AI payload per case → executor → code check → AI review
8  UAT review + sign-off   CCRE team first; failures → "correct the M2C" → back to step 3 (cycle +1)
                           all pass → business signs off
9  RTP                     Export bundle → Support uploads to CCRE → CCRE team confirms
```

Timeline milestones follow the same sequence: **rule config + DMG changes → sanity check → UAT test case prep → UAT test case review → UAT execution → UAT review and sign-off → RTP**. Actual dates are recorded automatically as the onboarding moves, and they feed the KPIs.

### PM questionnaire (structured)

Requested RTP date · earliest start · CCRE team members · DMG changes needed · package rebuild lead time · business review days · business sign-off days · UAT environment ready · blackout dates · priority · notes. The AI starts from a deterministic baseline estimate. Every plan is checked (7 milestones, in order, no weekends or blackout dates), and a plan that misses the requested RTP is flagged **at risk** rather than compressed.

### UAT execution and verdicts

For each business-approved test case:

1. The `payload_generator` agent adapts the sample payload. CRMS `ShpPcdDetailsMsg` requests are mapped field by field: country criterion, Import/Export, destination, services, B2B/B2C class, value, currency, incoterm, weight.
2. The request is sent to the chosen endpoint.
3. The deterministic checker reads the response using the endpoint's paths. For CRMS that's the declaration codes at `MvmtMsg.Bd.Mvmt[].PcsInMvmt[].RqrReglDecTy[].TyCd` (`-` = none) and the service status `MvmtMsg.RespStatus[].Sev` = `10`.
4. Optionally, the same request goes to a **comparison endpoint**, and the responses are diffed with the suite's own `findDifferences` logic, ignoring `Hdr`.

**When the checker can read the response, code decides the verdict.** Otherwise the AI reviewer decides, and the result is marked as decided by AI.

**The screen shows results only:** test, what is tested, PASS/FAIL, why, and the environment comparison. The evidence is **downloaded**:

- **Request** and **Response** buttons per test, plus the comparison file when one ran.
- **Download all (zip)** per run, containing `summary.xlsx`, `requests/`, `responses/` and `compare/`.

The business team can download too, once the CCRE team has accepted the results. Credentials never appear in any download. The `failure_analyst` agent diagnoses a failed result on request.

---

## Agents (8)

| Agent | Stage | Output |
|---|---|---|
| `intake_assistant` | Intake (chat) | IntakeTurn → BusinessRequirement |
| `requirement_interpreter` | Intake (form + NLP) | RequirementInterpretation |
| `timeline_planner` | Timeline | TimelinePlan (7 milestones) |
| `rule_drafter` | Rule config | ChangeSet → staged proposal, human accepts |
| `test_case_designer` | UAT prep | TestCaseSuite with business summaries |
| `payload_generator` | UAT execution | GeneratedPayload |
| `response_reviewer` | UAT execution | ResponseReview |
| `failure_analyst` | UAT review | FailureAnalysis |

The root `ccre_orchestrator` behind **Ask Expert** (internal users only) delegates to the interpreter, drafter, test designer and failure analyst, and uses the read-only catalogue and validation tools.

---

## KPIs

Onboardings, completed, average lead time, **milestones on time %**, average milestone slip, **M2C first-time-right %**, **average UAT cycles**, **first-run pass rate**, **rule coverage %**, defects found by the CCRE side vs the business, and average review wait time. Each one is computed from the audit trail and the stored artifacts, not entered by hand. The KPIs page defines every number.

---

## Layout

```
agent.py                 ADK entry point: 8 sub-agents + root orchestrator
components/              Template LLM gateway, logging, tracing (stub_llm.py scripts all 8 agents offline)
prompts/                 Root and base prompts
tools/agents/            Agent builders, prompts/*.md, output schemas
tools/functions/         Read-only FunctionTools + server-only staging
tools/core/              Config, ORM model, condition grammar, export, security (users/tokens)
tools/ingestion/         M2C workbook + sir-configuration parsers
tools/validation/        16-check deterministic register
tools/workflow/          Lifecycle state machine + per-case gate facts + M2C draft
tools/timeline/          Questionnaire, baseline estimator, plan validation
tools/execution/         Evaluator, payload builders (incl. crms.py — onboarded CRMS suite), mock CCRE, executors, checker, custom/
server/                  app.py, auth.py, admin.py, endpoints.py, lifecycle.py, uat.py, downloads.py, kpis.py, advisory.py, routes.py, cli.py
ui/                      Single-page app (sign-in, workspace, business view, KPIs, admin)
config/                  .env.example · .env.apigee · .env.stub
tests/                   Suite by category; root conftest.py writes test_report.xlsx
```

**M2C scope:** the draft covers the Import tab. The other M2C tabs that power it are deliberately deferred and will be configured next.

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CCRE_LLM_MODE` | `apigee` (`.env.stub`: `stub`) | `stub` · `openai` · `google-ai` · `apigee` |
| `AUTH_MODE` | `users` | `users` = sign-in + RBAC; `none` = development only |
| `CCRE_ADMIN_EMAIL` / `CCRE_ADMIN_PASSWORD` | `admin@ccre.local` / `ChangeMe123!` | First admin, created when no user exists |
| `CCRE_SECRET_KEY` | generated in `.ccre_data\secret.key` | Token signing secret |
| `CCRE_UAT_EXECUTOR` | `mock` | Fallback when no Admin endpoint is chosen: `mock` · `http` · `package.module:Class` |
| `CCRE_UAT_ENDPOINT`, `CCRE_UAT_AUTH_HEADER`, `CCRE_UAT_TIMEOUT_SECONDS` | — | Fallback `http` mode only; prefer Admin endpoints |
| `CCRE_UAT_GROUPS_PATH`, `CCRE_UAT_CASE_CREATED_PATH` | `requirements[].group`, `caseCreated` | Where the response says what was raised |
| `CCRE_DATABASE_URL` | SQLite `.ccre_data\ccre_v2.db` | Any SQLAlchemy URL |
| `CCRE_REFERENCE_DIR` | `..\Reference` | Workbook and package location |
| `APIGEE_*` | — | DHL GenAI Gateway; see `config\.env.apigee` |

---

## Tests

```powershell
pytest                 # offline (stub LLM, AUTH_MODE=none + role headers); writes test_report.xlsx
```

The suite includes a full DE onboarding from intake to RTP, the UAT failure → correction → second-cycle loop, intake by chatbot, the BG package-gap block, RBAC with real sign-in, and the admin panel. Tests that need the reference files skip cleanly without them. See **QUICK_START.md** for a walkthrough and **TROUBLESHOOTING.md** for fixes.
