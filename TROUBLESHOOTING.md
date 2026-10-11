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
| `/api/*` returns **401** | `AUTH_MODE=apikey` | Send `Authorization: Bearer <CCRE_API_KEY>` or `X-API-Key` |
| "Address already in use :8000" | Another server is running | Stop it, or use `--port 8001` |
| UI "Test Report" says no report | `pytest` has not run yet | Run `pytest`; it writes `test_report.xlsx` |
| Want a clean database | — | Stop the server and delete `.ccre_data\`, then `ccre bootstrap` |
| `KeyError: Context variable not found` from ADK | A prompt contains `{some_name}` | Run `python patch_adk.py`; the server also patches this in-process |
