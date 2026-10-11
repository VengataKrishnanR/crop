# CCRE Rules Intelligence & Onboarding Platform — v2

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

### Plug in your API test-execution code

UAT runs against a built-in **mock CCRE** endpoint until you configure the real one. See **`tools/execution/custom/README.md`**: wrap your code in a class with `execute(payload) -> {"status", "body"}` and set `CCRE_UAT_EXECUTOR=tools.execution.custom.<module>:<Class>`. Then upload your **sample payload** on the UAT execution screen.

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
1  Requirement intake      Business / CCRE: chatbot or form + NLP     → CCRE consultant approves
2  Timeline                AI plans from PM questionnaire              → PM approves → published to business
3  Rule config + DMG       CCRE team: M2C draft (seeded from workbook) + AI conversion, validated
4  Sanity check            Validator clean + package complete (gate cannot be waived)
5  UAT test case prep      AI writes cases from the M2C (may start during step 3)
6  UAT test case review    CCRE team first → then business team
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

1. The `payload_generator` agent adapts the sample payload.
2. The executor sends it (mock, `http`, or your own code).
3. The deterministic checker reads the response using `CCRE_UAT_GROUPS_PATH` and `CCRE_UAT_CASE_CREATED_PATH`.
4. The `response_reviewer` agent explains the result.

**When the checker can read the response, code decides the verdict.** Only when it cannot does the AI's verdict stand, and the result is marked as decided by AI. The `failure_analyst` agent diagnoses any failed result on request.

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
tools/execution/         Evaluator, payload builder, mock CCRE, executors, response checker, custom/
server/                  app.py, auth.py, admin.py, lifecycle.py, uat.py, kpis.py, advisory.py, routes.py, cli.py
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
| `CCRE_UAT_EXECUTOR` | `mock` | `mock` · `http` · `package.module:Class` |
| `CCRE_UAT_ENDPOINT`, `CCRE_UAT_AUTH_HEADER`, `CCRE_UAT_TIMEOUT_SECONDS` | — | For `http` |
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
