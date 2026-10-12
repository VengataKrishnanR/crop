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
| Reminder: “No active user has the … role” | Nobody holds the approver role (for that country) | Admin → add a user with that role |
| Reminder: “sent less than 10 minutes ago” | Reminders are throttled per stage | Wait, or contact the approver directly |
| Emails do not arrive | No SMTP host — they are in the outbox | Admin → Email → set the SMTP host and **Send test**; check *Sent emails* for FAILED + reason |
| DMG: “A second CCRE team member must review” | Four-eyes rule on the DMG email | Ask another CCRE team member / consultant to approve |
| DMG: “Set the DMG recipients … first” | The template has no To address | Rule config → DMG email template and recipients → To → Save template |
| “Submit rule config” is blocked by DMG | The DMG task is not completed | Approve and send the DMG email, or have a CCRE consultant mark it not required |
| Test cases cannot be approved as a stage | Some rows still need a decision | Approve / Reject every row (or **Approve all waiting**) |
| “N M2C row(s) still have errors” | A row has an authoring error | Rule config → Rules: rows marked ✕ Error — open, fix, Save row |
| Row is “⚠ Package gap” | The config package does not ship / map the group or definition for the country | Rule config → Package coverage → **Package request (.csv)** to Support; load the new package when it arrives |
| “Rows can only be edited while … Rule configuration” | The onboarding moved on | Reject back to rule configuration (sanity check or UAT review) to correct |
| Consultant cannot submit the requirement | Only the business submits its own requirement | The business user clicks **Submit requirement for approval** |
| PM cannot submit the timeline | The consultant submits; the PM approves | The CCRE consultant clicks **Submit timeline for PM approval** |
| An action button is greyed out | A gate is not met | The reason is printed under the button (e.g. validation blockers, no test results) |
| Endpoint **Test** says “Not reachable” | No route to the host | Connect to the DHL VPN; for `*.dhl.com` the corporate proxy is bypassed automatically |
| Endpoint **Test** returns HTTP 401/403 | Wrong or expired key | Admin → Edit → enter the key again → Update endpoint |
| Run fails with “credential … can no longer be read” | `.ccre_data\secret.key` or `CCRE_SECRET_KEY` changed | Admin → Edit the endpoint and re-enter the key |
| UAT results are all FAIL against your real endpoint | The response paths differ | Admin → Edit the endpoint → *Response mapping*: set where the response lists what was raised (or apply a preset) |
| UAT results show "decided by AI reviewer" | The checker could not read the response | Same fix as above, so code can decide |
| "Address already in use :8000" | Another server is running | Stop it, or use `--port 8001` |
| UI "Test Report" says no report | `pytest` has not run yet | Run `pytest`; it writes `test_report.xlsx` |
| Want a clean database | — | Stop the server, delete `.ccre_data\ccre_v2.db`, then `ccre bootstrap` (or `START.bat`) |
| `KeyError: Context variable not found` from ADK | A prompt contains `{some_name}` | Run `python patch_adk.py`; the server also patches this in-process |
