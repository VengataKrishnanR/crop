# CCRE Rules Intelligence & Onboarding Platform

A Google ADK application for onboarding a country's customs requirements into **CCRE** (Customs Clearance Rule Engine). It ingests the M2C rule workbook and the GCCP `sir-configuration` package, validates the rule layer deterministically, gates every release on named human approvals, and exports the handover bundle that Support uploads.

An ADK advisory layer of four specialist agents helps along the way. **Agents recommend, code validates, humans approve.** No agent can approve, transition a case, seal a rule set, or reach CCRE, because no tool for any of those exists.

> Built on the company ADK template (`final_rework`): same layout, the same `components/` LLM gateway (DHL Apigee / stub / OpenAI / Google AI), and the same server, UI and test-report conventions.

---

## How to run

### What you need

- **Windows** with **Python 3.11 or newer**. Check with `python --version`.
- The **reference files** in a folder named `Reference` **next to** this folder:

  ```
  CCRE Rules Intelligence & Support Plaform\
  ├── Reference\                  ← sir-configuration*.zip (or folder) and M2c*.xlsx
  └── ccre-onboarding-agent\      ← this application
  ```

- For real AI answers only: a **DHL Apigee API key** and a connection to the **DHL network/VPN**. Without them the app runs in offline mode.

### Option 1 — one click (easiest)

1. Open the `ccre-onboarding-agent` folder.
2. Double-click **`START.bat`**.
3. Wait for `Open your browser at: http://localhost:8000`. The first run installs packages and takes a few minutes.
4. Open **http://localhost:8000** in your browser.

`START.bat` does everything for you: it creates the Python environment, installs packages, sets offline mode if there is no `.env`, loads the files from `..\Reference`, and starts the server. Press **Ctrl+C** in that window to stop it.

### Option 2 — step by step (PowerShell)

Run these in a PowerShell window:

```powershell
# 1. Go to the application folder
cd "C:\Users\Vengata Krishnan R\OneDrive\Desktop\CCRE Rules Intelligence & Support Plaform\ccre-onboarding-agent"

# 2. Create and activate the virtual environment (first time only for the create step)
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # your prompt now starts with (.venv)

# 3. Install (first time only)
pip install -r requirements.txt
pip install -e .
python patch_adk.py

# 4. Pick the AI mode (first time only) — offline, no key needed
copy config\.env.stub .env

# 5. Load the workbook and package from ..\Reference
ccre bootstrap

# 6. Start the server
uvicorn server.app:app --port 8000
```

Open **http://localhost:8000**. Leave the PowerShell window open while you use the app; press **Ctrl+C** to stop it.

If step 2 fails with *"running scripts is disabled"*, run this once and retry:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### Every time after the first

```powershell
cd "C:\Users\Vengata Krishnan R\OneDrive\Desktop\CCRE Rules Intelligence & Support Plaform\ccre-onboarding-agent"
.\.venv\Scripts\Activate.ps1
uvicorn server.app:app --port 8000
```

Or just double-click `START.bat` again.

### Switch to real AI (DHL GenAI Gateway)

Offline mode gives scripted agent answers. For real ones, connect to the DHL VPN, then:

```powershell
copy config\.env.apigee .env
$env:APIGEE_API_KEY = "paste-your-key-here"
uvicorn server.app:app --port 8000
```

`$env:` lasts only for that PowerShell window. To keep the key, add a line `APIGEE_API_KEY=your-key` to `.env`, and never commit or share that file. To go back offline, run `copy config\.env.stub .env` and restart.

### Check it works

| Open | You should see |
|---|---|
| http://localhost:8000 | The CCRE UI; the badge at top right says **Online · LLM stub** (or `apigee`) |
| http://localhost:8000/docs | Interactive API documentation |
| http://localhost:8000/api/health | `{"status":"ok", ...}` with the loaded package |

### Use it — a 2-minute walkthrough

1. **Requirement** tab → **+ New** → create a case, e.g. `ONB-2026-BG-014`, country `BG`, title *BG IOSS trigger*.
2. Paste a requirement, e.g. *BG B2C shipments need IOSS when SDT is present and the service code is not DD.*, and click **Interpret**.
3. Read the result, especially the ambiguities, then click **Draft rules**.
4. In the yellow panel, pick a rule set, type your name, and click **Accept proposal**. The rules are written and validation runs immediately.
5. **Rule set** tab → **Validate**, **Design tests**, **Export**.
6. **Failure** tab → enter a failed test id and what happened → **Analyse failure**.
7. **Ask Expert** (top right) → ask anything, e.g. *Package status for BG*.

### Optional: other ways to run

| Task | Command (with the venv active) |
|---|---|
| Run all tests + create `test_report.xlsx` | `pytest` |
| Validate a rule set from the command line | `ccre validate <rule_set_id>` |
| Check one condition expression | `ccre expr "!serviceCodeList.contains(\"DD\")"` |
| Google's ADK developer UI | `adk web . --port 8002`, then open http://localhost:8002 |
| Use a different port | `uvicorn server.app:app --port 8001` |
| Start again with an empty database | stop the server, delete the `.ccre_data` folder, run `ccre bootstrap` |

### Common problems

| Problem | Fix |
|---|---|
| `ccre` or `uvicorn` "is not recognized" | The venv isn't active. Run `.\.venv\Scripts\Activate.ps1` first |
| `ccre bootstrap` says "need both artifacts" | Put the `sir-configuration*` package and `M2c*.xlsx` workbook in `..\Reference` |
| Agent buttons show "LLM not configured" | You're in `apigee` mode without a key. Set `APIGEE_API_KEY`, or `copy config\.env.stub .env` |
| "unauthorized network" (403) | Connect to the DHL VPN |
| "Address already in use" | Something else uses port 8000. Close it, or use `--port 8001` |

More in **TROUBLESHOOTING.md**.

---

## Layout

```
ccre-onboarding-agent/
├── agent.py                  ADK entry point — root_agent (ccre_orchestrator) for `adk web`
├── prompts/                  root_agent.md, base_agent.md
├── components/               Template infrastructure (unchanged contract)
│   ├── llm/                  build_model_for_env(): stub | openai | google-ai | apigee
│   ├── logging/              configure_logging()
│   └── tracing.py            ADK Web trace display fix
├── tools/
│   ├── agents/               4 sub-agent builders + prompts/*.md + output schemas
│   ├── functions/            FunctionTools: catalogue lookups, check_expression, validate_rule_set…
│   ├── core/                 config, SQLAlchemy model, condition grammar, export bundle
│   ├── ingestion/            M2C workbook + sir-configuration package parsers
│   ├── validation/           The 16-check deterministic register (the platform's authority)
│   └── workflow/             Onboarding-case state machine and release gates
├── server/
│   ├── app.py                FastAPI: /api/* + agent endpoints + UI facade + static UI
│   ├── routes.py             Domain routes (ingest, catalogue, cases, rules, validate, export)
│   ├── advisory.py           AdvisoryService — runs agents, validates, audits, stages
│   ├── agent_invoker.py      Run an agent; JSON extraction with one repair retry
│   ├── artifact_schemas.py   Validators for agent output
│   └── cli.py                `ccre` command (bootstrap, validate, expr, …)
├── ui/                       Single-page UI (DHL template styling)
├── config/                   .env.example · .env.apigee · .env.stub
├── tests/                    147 tests, categorised by marker
├── conftest.py               Writes test_report.xlsx on every pytest run
├── START.bat                 One-click setup + start (Windows)
└── patch_adk.py              Brace pass-through patch for ADK prompts
```

The reference artifacts are read from `..\Reference` (the folder beside this one). Override with `CCRE_REFERENCE_DIR`.

---

## The agents

| Agent | Input | Output (validated) | Tools | Human gate after it |
|---|---|---|---|---|
| `requirement_interpreter` | Requirement text / email | `RequirementInterpretation` | `list_requirement_groups`, `country_package_status` | PM approves the reading |
| `rule_drafter` | Approved interpretation | `ChangeSet`, staged as `PROPOSED` | `find_similar_rules`, `country_package_status`, `get_requirement_definition`, `list_requirement_groups`, `check_expression` | A named person accepts; the validator runs immediately |
| `test_case_designer` | Rule set (+ country) | `TestCaseSuite` | `find_similar_rules`, `get_requirement_definition`, `check_expression` | Reviewer approves the suite |
| `failure_analyst` | Failed test details | `FailureAnalysis` | `get_requirement_definition`, `country_package_status`, `check_expression`, `find_similar_rules` | Recommendation only |

`ccre_orchestrator` (root) holds the four agents as `AgentTool`s and the read-only FunctionTools. It is what the UI's **Ask Expert** chat and `adk web` talk to.

Every agent output is parsed against its pydantic schema. A malformed reply gets one repair retry with the exact error fed back, and each result is written to the case audit trail as `agent:<name>`. The drafter's `ChangeSet` is staged by the server, not by the agent, so no agent holds a write tool.

---

## API (all under `/api`; interactive docs at `/docs`)

| Area | Endpoints |
|---|---|
| Meta | `GET /health`, `GET /checks`, `GET /agents` |
| Ingest | `POST /ingest/package`, `POST /ingest/workbook` |
| Catalogue | `GET /catalog/groups`, `/catalog/definitions/{sir_id}`, `/catalog/countries/{cc}/status`, `/catalog/permitted` |
| Cases & workflow | `POST/GET /cases`, `GET /cases/{id}`, `PUT /cases/{id}/approved-rtp`, `GET /cases/{id}/transitions`, `POST /cases/{id}/transition`, `GET /cases/{id}/audit` |
| Rules | `GET /rule-sets`, `GET /rule-sets/{id}/rules`, `PATCH /rules/{id}`, `PATCH /bindings/{id}` |
| Validation | `POST /rule-sets/{id}/validate`, `POST /expressions/check`, `GET /validation-runs/{id}` |
| **Agents** | `POST /cases/{id}/interpret`, `POST /cases/{id}/draft-rules`, `POST /rule-sets/{id}/test-suite`, `POST /failures/analyse` |
| Proposals | `GET /cases/{id}/proposals`, `POST /proposals/{id}/decide` |
| Export | `GET /rule-sets/{id}/export`, `POST /rule-sets/{id}/seal`, `POST /rule-sets/{id}/fork` |
| UI facade | `POST /session`, `POST /run` (chat), `GET /test-report/xlsx` |

There is deliberately no endpoint that uploads to CCRE.

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `CCRE_LLM_MODE` | `apigee` (`.env.stub` sets `stub`) | `stub` · `openai` · `google-ai` · `apigee` |
| `APIGEE_API_KEY`, `APIGEE_PROXY_URL_*`, `APIGEE_DEFAULT_*_MODEL` | — | DHL GenAI Gateway; see `config/.env.apigee` |
| `CCRE_DATABASE_URL` | SQLite in `.ccre_data/ccre.db` | Any SQLAlchemy URL (Postgres-compatible model) |
| `CCRE_REFERENCE_DIR` | `..\Reference` | Where `ccre bootstrap` finds the workbook and package |
| `CCRE_AGENTS_ENABLED` | `1` | `0` switches the advisory layer off (the rest still works) |
| `CCRE_AGENT_TIMEOUT_SECONDS` | `120` | Upper bound per agent run |
| `AUTH_MODE` / `CCRE_API_KEY` | `none` | `apikey` requires the key on every `/api/*` call except health |
| `LOG_LEVEL` | `INFO` | Root log level |

---

## Tests

```powershell
pytest                 # full suite, offline (the stub LLM is forced), writes test_report.xlsx
bash scripts/ci.sh     # same, for CI
```

Categories (one sheet each in the XLSX): Smoke · Grammar · Validation · Ingestion · Workflow · API · Agents · E2E Positive · E2E Negative. Tests that need the real artifacts skip cleanly when `..\Reference` is absent.

See **QUICK_START.md** to run it, and **TROUBLESHOOTING.md** when something goes wrong.
