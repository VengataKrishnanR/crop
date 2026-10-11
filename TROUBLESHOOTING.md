# Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ccre` / `uvicorn` "is not recognized" | The venv is not active, so its `Scripts` folder is not on PATH | `.\.venv\Scripts\Activate.ps1` (prompt shows `(.venv)`), or call `.\.venv\Scripts\ccre.exe` directly |
| `Activate.ps1 cannot be loaded… running scripts is disabled` | PowerShell execution policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, once |
| `ModuleNotFoundError: google.adk` / `tools` / `server` | Dependencies or the editable install are missing | `pip install -r requirements.txt` then `pip install -e .` |
| `ccre bootstrap`: "need both artifacts; looked in …" | `..\Reference` has no `sir-configuration*` package or `M2c*.xlsx` workbook | Put both in `..\Reference`, set `CCRE_REFERENCE_DIR`, or pass `--package` / `--workbook` |
| Agent endpoints return **503** "LLM not configured: environment variable 'APIGEE_API_KEY'…" | `CCRE_LLM_MODE=apigee` without a key | Set `APIGEE_API_KEY`, or `copy config\.env.stub .env` for offline mode, then restart |
| Agent endpoints return **503** "Advisory layer disabled" | `CCRE_AGENTS_ENABLED=0` | Remove it or set it to `1` |
| Agent endpoints return **502** "LLM returned 403 … unauthorized network" | Not on the DHL network | Connect to DHL VPN; see the proxy notes in `config\.env.apigee` |
| **502** "Agent failed after retry" | The model returned output that did not match the schema twice | Retry; if persistent, try another deployment in `APIGEE_DEFAULT_AZURE_OPENAI_MODEL` |
| **502** "Agent invocation timeout" | Slow gateway | Raise `CCRE_AGENT_TIMEOUT_SECONDS` |
| Sign-in says the password is wrong for `admin@ccre.local` | The admin password was changed, or `CCRE_ADMIN_PASSWORD` differed on first start | Ask another admin to reset it in Admin; or (losing all data) delete `.ccre_data\ccre_v2.db` and restart |
| A user gets **403** "needs one of these roles" | Their role does not own that step | Change the role in Admin, or have the right person do it |
| A business user sees no onboardings | No countries assigned | Admin → set their countries (e.g. `DE`) → Save |
| An action button is greyed out | A gate is not met | The reason is printed under the button (e.g. validation blockers, no test results) |
| UAT results are all FAIL against your real endpoint | The response paths differ | Set `CCRE_UAT_GROUPS_PATH` / `CCRE_UAT_CASE_CREATED_PATH` to where your response lists the raised requirements |
| UAT results show "decided by AI reviewer" | The checker could not read the response | Same fix as above, so code can decide |
| "Address already in use :8000" | Another server is running | Stop it, or use `--port 8001` |
| UI "Test Report" says no report | `pytest` has not run yet | Run `pytest`; it writes `test_report.xlsx` |
| Want a clean database | — | Stop the server, delete `.ccre_data\ccre_v2.db`, then `ccre bootstrap` (or `START.bat`) |
| `KeyError: Context variable not found` from ADK | A prompt contains `{some_name}` | Run `python patch_adk.py`; the server also patches this in-process |
