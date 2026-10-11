# CCRE Onboarding — Quick Start (5 Minutes)

## Option A — one click (Windows)

Double-click **`START.bat`**. It will:

1. create `.venv` (first run only),
2. copy `config\.env.stub` to `.env` if you have no `.env` (offline mode, no key needed),
3. install the dependencies and patch ADK,
4. load the workbook and package from `..\Reference` (`ccre bootstrap`),
5. start the server.

Then open **http://localhost:8000**.

---

## Option B — step by step (PowerShell)

### 1. Create the virtual environment
```powershell
cd ccre-onboarding-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
If PowerShell blocks the script: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, once.

### 2. Install
```powershell
pip install -r requirements.txt
pip install -e .
python patch_adk.py
```

### 3. Choose the LLM mode
```powershell
copy config\.env.stub .env       # offline: scripted agents, no key, no VPN
# — or —
copy config\.env.apigee .env     # DHL GenAI Gateway (needs DHL network/VPN)
$env:APIGEE_API_KEY = "your-key-from-the-AI-champion"
```

### 4. Load the reference artifacts
```powershell
ccre bootstrap
```
Expected: package 2.10.4-beta.2 and workbook 2.10.9-beta.2 load, and the validator reports **3 blockers** with the gate **LOCKED**.

### 5. Start
```powershell
uvicorn server.app:app --port 8000
```
- UI: **http://127.0.0.1:8000**
- API docs: **http://127.0.0.1:8000/docs**
- ADK dev UI (optional): `adk web . --port 8002` (pick `agent` in the list)

---

## Walkthrough in the UI

1. **Requirement** tab: click **+ New** and create a case (e.g. `ONB-2026-BG-014`, `BG`, *BG IOSS trigger*).
2. Paste: *BG B2C shipments need IOSS when SDT is present and the service code is not DD.* Click **Interpret**.
3. Review the reading, especially the ambiguities. Click **Draft rules**.
4. In the yellow gate panel, choose the rule set, enter your name, and click **Accept proposal**. The rules are written and the validator runs at once.
5. **Rule set** tab: **Validate**, **Design tests**, **Export**.
6. **Failure** tab: enter a failed test id and what happened, then **Analyse failure**.
7. **Ask Expert** (top right): free-form questions, such as *Package status for BG* or *Check: matchCiMask("shortCode,==,SDT")*.

---

## Essential commands

| Task | Command |
|---|---|
| Activate venv | `.\.venv\Scripts\Activate.ps1` |
| Load reference data | `ccre bootstrap` |
| Validate a rule set | `ccre validate <rule_set_id>` |
| Check one expression | `ccre expr "!serviceCodeList.contains(\"DD\")"` |
| List the checks | `ccre checks` |
| Start server | `uvicorn server.app:app --port 8000` |
| Run tests (+ XLSX report) | `pytest` |
| Health | `curl http://127.0.0.1:8000/api/health` |
