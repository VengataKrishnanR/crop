# Agent design

Oct 21, 2026 · @VengataKrishnanR

> Exported from the Claude Doc "CCRE Onboarding Agent — Production System Design"
> (https://claude.ai/artifact/C6fbzc4E6ym53JbwuMNwM9), tab "Agent design", rev 21.
> The two embedded diagrams (one agent job; feedback loops) are not included in the Markdown export;
> they correspond to `ccre-agent-architecture.mmd` and `ccre-agent-harness-feedback.mmd`.

## The agent contract

Every agent is a pure "suggestion function": it reads context through read-only tools, returns one typed suggestion, and stops. Code validates the suggestion; a named human role accepts or rejects it. No agent ever changes case state, approves, sends email or calls CCRE.

Ten rules apply to all nine agents (8 specialists + root orchestrator):

1. **Single responsibility.** One agent, one stage, one output schema. No agent calls another agent; only the orchestrator delegates, and only for Ask Expert.
2. **Read-only tools.** Agents get tools that read case data, reference data and calendars. Writes happen only in application code after validation.
3. **Typed output envelope.** Every response is `{suggestion, rationale, assumptions[], open_questions[], confidence, sources[]}`, where `suggestion` follows the agent's own Pydantic schema.
4. **Cite or flag.** Every value in a suggestion must point to a source (requirement field, M2C row, package definition, calendar entry, CRMS response) or be listed in `assumptions`.
5. **Deterministic gate after every agent.** Grammar check, validation register, schema check or checker runs before a human ever sees the suggestion. Failures go back to the agent once with the error, then to the manual path.
6. **Human gate per stage.** The suggestion is stored as a *draft*; only the stage's approving role can accept it, and acceptance is an audited transition.
7. **Asynchronous by default.** Agents run as worker jobs with a timeout, an attempt limit and a dead-letter state; the UI polls or streams the job status.
8. **Never block the manual path.** If an agent is down, slow or wrong, every stage can still be completed by hand.
9. **Everything recorded.** Agent name, prompt version, model ID, input hash, tool calls, output, validation result, human decision and edit distance go to the agent run log.
10. **Untrusted input stays data.** Business free text, workbook cells and CRMS responses are passed as quoted data, never as instructions; the system prompt says so explicitly.

## Agent map

Eight specialists cover seven of the nine stages; stages 4 (sanity check) and 9 (RTP) stay fully deterministic on purpose.

| Stage | Agent | Produces | Deterministic gate after it | Human who accepts |
| --- | --- | --- | --- | --- |
| 1 Requirement intake | `intake_assistant` | Conversational capture; filled intake form draft | Required M2C Import columns present; pick-list values valid; condition builder accepts it | Business submits |
| 1 Requirement intake | `requirement_interpreter` | Structured requirement: SIR/SIRG intent, conditions, M2C field mapping, gaps | Condition grammar; values exist in workbook / active package | CCRE consultant approves or rejects |
| 2 Timeline | `timeline_planner` | 7-milestone plan with dates, risks | Plan validation: 7 milestones, ordered, no weekends or blackouts; at-risk flag | PM approves |
| 3 Rule config | `rule_drafter` | Proposed M2C Import rows and Other Logic | Other Logic grammar; package coverage; diff vs workbook | CCRE team accepts rows |
| 4 Sanity check | none | — | 6 automatic checks | CCRE approves / sends back |
| 5 UAT prep | `test_case_designer` | UAT test-case rows (positive, negative, boundary) | Row schema; each row traces to a rule row; no duplicates | CCRE team, then business (stage 6) |
| 7 UAT execution | `payload_generator` | CRMS `ShpPcdDetailsMsg` payload per test row | Payload schema; mapping rules in `crms.py` | None (executed automatically, evidence kept) |
| 7 UAT execution | `response_reviewer` | Verdict on cases the deterministic checker could not decide | Checker always runs first; reviewer only on "undecided" | CCRE team at stage 8 |
| 8 UAT review | `failure_analyst` | Root-cause hypothesis and fix suggestion per failed row | Must reference rule row, payload field or response element | CCRE team decides loop-back to stage 3 |
| All (internal) | `ccre_orchestrator` | Answers for Ask Expert, with citations | Answer must cite case or reference data | Read only, no acceptance needed |

## Runtime: one agent job

Every agent, whatever its stage, runs through the same pipeline, so retries, logging and the human gate are built once.

[embedded content: one agent job · trigger to audited transition]

A failed gate gets one retry with the validator's message; a second failure hands the stage to the manual path, so a broken agent costs time, never a wrong rule.

## Agent 0 — `ccre_orchestrator` (Ask Expert)

Answers internal users' questions about a case or the rule engine by routing to the right specialist in *explain* mode, never in *act* mode.

| Field | Design |
| --- | --- |
| Users | PM, CCRE consultant, CCRE team, Admin. Not exposed to Business |
| Trigger | User question in the Ask Expert panel, optionally scoped to a case |
| Context | Case summary (stage, country, requirement, open approvals), user role and country scope |
| Tools | `get_case`, `search_m2c_rows`, `get_package_definition`, `resolve_sir`, `get_audit_history`, `get_uat_results` |
| Delegates to | Specialists in explain mode only (e.g. "why did this row fail?" → `failure_analyst`) |
| Output | `{answer, citations[], suggested_next_action?, out_of_scope: bool}` |
| Gate | Answer without at least one citation is shown as "unverified"; never offered as an action button |

**Steps**

1. Classify the question: case status · reference lookup · rule explanation · failure explanation · out of scope.
2. Enforce scope: refuse cases outside the user's country scope (checked in code before the LLM call).
3. Call reference tools or one specialist in explain mode.
4. Compose the answer with citations; offer a *link* to the relevant stage, never a button that acts.

**Guardrails:** no approve/reject/send tools exist in its toolset; rate-limited per user; answers logged with citations.

**Measure:** citation rate, "helpful" thumbs ratio, out-of-scope rate, p95 latency.

## Agent 1 — `intake_assistant` (stage 1)

Turns a business user's chat or free text into a complete intake form draft, asking only for what is missing.

| Field | Design |
| --- | --- |
| Users | Business (country-scoped) |
| Trigger | Chat message, or "Fill the form from my text" |
| Context | Current form state; list of required M2C Import columns with accepted values; requirement groups from the active config package; country |
| Tools | `get_intake_fields`, `get_picklist(field, country)`, `get_requirement_groups(package_version)`, `check_condition(expression)` |
| Output | `{fields: {name: {value, source_span, confidence}}, missing_fields[], clarifying_question?, condition_draft?}` |
| Gate | Pick-list membership; condition builder refuses what one M2C row cannot hold; required-field completeness |
| Human | Business reviews the form and presses Submit; nothing auto-submits |

**Steps**

1. Extract candidate values from the text; keep the exact text span each came from.
2. Map each to a field; snap to the nearest pick-list value only when unambiguous, else list it as a question.
3. Draft the condition in builder form (value / weight / logic) and pre-check it with `check_condition`.
4. If required fields are still missing, ask **one** clarifying question at a time, most blocking first.
5. Return the draft; the UI highlights AI-filled fields so the user can see and edit them.

**Failure handling:** invalid pick-list value → field left empty and asked; condition rejected by the builder → explain why in business words and suggest splitting into two requirements.

**Measure:** fields filled correctly without edit, questions per completed form, time to submit, condition rejection rate.

**Eval cases:** clean single-SIR request; multi-condition request that must be split; text in mixed language; text containing an instruction-like sentence (prompt injection test).

## Agent 2 — `requirement_interpreter` (stage 1, consultant review)

Converts the submitted business requirement into a precise, engine-ready interpretation the CCRE consultant can approve or reject in minutes.

| Field | Design |
| --- | --- |
| Users | CCRE consultant (reads the result) |
| Trigger | Business submits the intake form (job enqueued on the transition) |
| Context | Submitted form; similar existing M2C rows for the country; active package definitions; `sirdb` resolution for the SIR/SIRG |
| Tools | `search_m2c_rows(country, sir)`, `resolve_sir(country, code)`, `get_package_definition(version, id)`, `check_condition`, `find_similar_requirements` |
| Output | `{interpretation: {sir, sirg, import_columns{}, conditions[], other_logic_hint}, existing_rule_impact[], conflicts[], gaps[], questions_for_business[]}` |
| Gate | Every column value valid against workbook + active package; conflicts computed by code, not trusted from the LLM |
| Human | CCRE consultant approves (→ stage 2) or rejects with reason (→ business) |

**Steps**

1. Restate the requirement as engine terms: which SIR/SIRG, which M2C Import columns, which conditions.
2. Look up existing rows for the same country and SIR to detect *new*, *change* or *duplicate*.
3. Check the active package has the requirement definition the rule needs; if not, flag a package gap (e.g. today's missing BG IOSS).
4. List gaps and questions the business must answer before configuration.
5. Code then recomputes conflicts and package coverage and overrides anything the agent got wrong.

**Failure handling:** cannot resolve SIR → interpretation marked incomplete with the exact lookup that failed; never invents a definition ID.

**Measure:** consultant approval without edits, rejection reasons by category, gaps found later at sanity check (should trend to 0).

**Eval cases:** DE POA (definition missing in loaded package), BG IOSS (absent from package), a pure duplicate of an existing row, a change to an expiry date.

## Agent 3 — `timeline_planner` (stage 2)

Adjusts the deterministic baseline plan with reasoning the PM can accept or edit; the baseline estimator remains the anchor, not the LLM.

| Field | Design |
| --- | --- |
| Users | PM (owns, edits and approves the timeline) |
| Trigger | PM completes the structured questionnaire and asks for an AI plan |
| Context | Questionnaire answers; deterministic baseline (7 milestones); blackout calendar and weekends; requested go-live date; historical lead times per stage from the audit trail |
| Tools | `get_baseline_plan(case)`, `get_calendar(country, range)`, `get_historical_stage_durations(country?, complexity)`, `validate_plan(plan)` |
| Output | `{milestones[7]: {name, start, end, reason}, risks[]: {milestone, risk, mitigation}, at_risk: bool, deviations_from_baseline[]}` |
| Gate | `validate_plan`: exactly 7 milestones, ordered, no weekend or blackout dates; at-risk computed by code against the requested go-live |
| Human | PM edits and approves in one step |

**Steps**

1. Start from the baseline; never generate dates from scratch.
2. Adjust only where the questionnaire or history justifies it (e.g. a package gap adds a wait for a new beta; many UAT rows lengthen stage 7).
3. Explain every deviation from the baseline in one line.
4. Name the top risks with a mitigation each.
5. Call `validate_plan` itself and fix violations before returning; code validates again.

**Failure handling:** invalid plan after one retry → show the baseline with the agent's risk notes only.

**Measure:** PM edits per plan, on-time % of milestones versus plan, accuracy of the at-risk flag.

**Eval cases:** go-live inside a blackout window; requested date shorter than baseline; dependency on a new beta package.

## Agent 4 — `rule_drafter` (stage 3)

The highest-risk agent: it proposes the M2C Import rows that will become production customs rules, so it gets the strictest gates and the largest evaluation set.

| Field | Design |
| --- | --- |
| Users | CCRE team in the rule configuration workspace |
| Trigger | "Propose rows" in the workspace for an approved requirement |
| Context | Approved interpretation; live workbook rows for the country; `sirdb.v_import_final`; active package definitions and requirement-definition bindings; Other Logic grammar spec; 3–5 approved example rows of the same SIR type |
| Tools | `search_m2c_rows`, `resolve_sir`, `get_package_definition`, `get_requirement_bindings`, `check_other_logic(expr)`, `diff_against_workbook(rows)`, `package_coverage(rows)` |
| Output | `{rows[]: {action: add\|change\|expire, target_row_id?, columns{}, other_logic, binding_ids[], rationale, sources[]}, package_gaps[], support_request_needed: bool}` |
| Gate | Other Logic grammar; every column valid; bindings exist in the active package; diff vs workbook computed by code; package coverage computed by code |
| Human | CCRE team accepts, edits or discards each row individually; accepted rows enter the draft, then the sanity check (stage 4) |

**Steps**

1. Decide per need: add a new row, change an existing row, or expire one. Prefer change over add when an equivalent row exists.
2. Copy the column pattern from the closest approved example of the same SIR type (few-shot from real data, not invented).
3. Write Other Logic and validate it with `check_other_logic`; fix and recheck until it passes or give up with the error.
4. Bind each row to requirement definitions; run `package_coverage`; if a definition is missing, set `support_request_needed` and list the gap instead of guessing an ID.
5. Run `diff_against_workbook` and explain every changed cell.

**Guardrails:** cannot touch rows of other countries; cannot expire rows without an interpretation that says so; every cell carries a source; temperature 0.

**Failure handling:** grammar or binding still failing after one retry → row returned as "needs manual completion" with the failing part highlighted.

**Measure:** rows accepted unedited, cells edited per row, sanity-check pass rate on first run, UAT failures traced to drafted rows.

**Eval cases:** DE POA and BG IOSS against both packages (2.10.4 and 2.10.9); change of an existing row; expiry; rule needing two rows; a request the grammar cannot express.

## Agent 5 — `test_case_designer` (stage 5)

Derives UAT test cases from the accepted rule rows so that every condition branch is exercised at least once.

| Field | Design |
| --- | --- |
| Users | CCRE team (prepares), then business (reviews at stage 6) |
| Trigger | Stage 5 opens, or "+ Add scenario" with a free-text description |
| Context | Accepted rule rows with conditions and Other Logic; requirement interpretation; existing test rows for the case; CRMS field catalogue |
| Tools | `get_rule_rows(case)`, `explain_condition(expr)` (returns the branches), `get_crms_fields`, `get_existing_test_rows(case)` |
| Output | `{rows[]: {id, title, type: positive\|negative\|boundary, rule_row_ref, branch_ref, given{}, expected: {sir_triggered, sirg?, outcome}, rationale}}` |
| Gate | Row schema; every rule row and every condition branch covered (coverage computed by code); no duplicate `given` sets |
| Human | Row-level two-stage review: CCRE team, then business |

**Steps**

1. Ask code for the branches of each condition (`explain_condition`), so coverage is measured, not guessed.
2. Per branch: one positive row; one negative row just outside the condition; boundary rows for thresholds (weight, value).
3. For "+ Add scenario", convert the user's text into one row and link it to the nearest rule row and branch.
4. Express inputs only in CRMS fields that exist in the catalogue.
5. Return the coverage table alongside the rows.

**Failure handling:** a branch the agent cannot cover is listed as *uncovered* for a human to write by hand.

**Measure:** branch coverage %, rows rejected in review, defects found per row in UAT.

**Eval cases:** weight threshold rule (boundary), value + country AND rule, OR rule with three alternatives, scenario text that contradicts the rule.

## Agent 6 — `payload_generator` (stage 7)

Fills only the *variable* part of each CRMS payload; the message skeleton and mapping rules stay in code (`tools/execution/crms.py`), so the LLM can never produce a structurally wrong message.

| Field | Design |
| --- | --- |
| Users | None directly; runs per approved test row |
| Trigger | "Run UAT" on approved rows (one job per row, own queue) |
| Context | Test row `given` values; CRMS field catalogue with types and allowed values; a valid sample `ShpPcdDetailsMsg`; target environment (TEST / UAT / mock) |
| Tools | `get_crms_fields`, `get_sample_payload`, `build_payload(values)` (code fills the template), `validate_payload(msg)` |
| Output | `{field_values{}, derived_values[]: {field, value, reason}, payload_hash}` |
| Gate | `build_payload` + `validate_payload`: schema, types, allowed values, mandatory fields; payload stored with hash as evidence |
| Human | None before execution (rows are already approved); results reviewed at stage 8 |

**Steps**

1. Map each `given` value to its CRMS field.
2. Derive realistic values for mandatory fields the test does not care about (addresses, piece IDs) from approved test-data pools, never random real customer data.
3. Hand values to `build_payload`; code assembles the XML/JSON message.
4. Validate; on failure, one retry with the validator message.

**Optimisation:** once a row's payload validates, cache it by row hash; re-runs and cycle +1 reuse it unless the row changed, saving cost and making re-runs reproducible.

**Measure:** first-pass validation rate, payloads rejected by CRMS, cost per row.

**Eval cases:** each CRMS field type; boundary weights; a row asking for a field value outside the allowed list (must refuse, not coerce).

## Agent 7 — `response_reviewer` (stage 7, fallback only)

Judges a CRMS/CCRE response only when the deterministic checker returns *undecided*; it never overrides a checker pass or fail.

| Field | Design |
| --- | --- |
| Users | CCRE team sees its verdicts at stage 8, clearly labelled "AI-reviewed" |
| Trigger | Checker result = undecided (unexpected structure, extra or missing elements, ambiguous status) |
| Context | Test row expectation; sent payload; full response; checker's reason for undecided; TEST vs UAT comparison when both ran |
| Tools | `get_test_row`, `get_payload(hash)`, `get_response(run_id)`, `compare_envs(row)` |
| Output | `{verdict: pass\|fail\|inconclusive, evidence[]: {response_path, observed, expected}, checker_improvement_hint?}` |
| Gate | Each evidence item must point to a real path in the response (verified by code); otherwise verdict forced to inconclusive |
| Human | CCRE team confirms every AI-reviewed verdict at stage 8; nothing reaches business sign-off unconfirmed |

**Steps**

1. Read why the checker could not decide.
2. Locate the elements that carry the SIR/SIRG outcome in the response.
3. Compare with the expectation; cite paths and values.
4. Suggest a checker rule (`checker_improvement_hint`) so the same pattern becomes deterministic next time.

**Design intent:** the share of undecided results should shrink every release as hints become checker rules; the reviewer is a learning loop for the checker, not a permanent judge.

**Measure:** undecided rate per release, human agreement with AI verdicts, hints turned into checker rules.

## Agent 8 — `failure_analyst` (stage 8)

Explains why a UAT row failed and where the fix belongs, so a loop back to stage 3 is targeted rather than a full re-check.

| Field | Design |
| --- | --- |
| Users | CCRE team deciding pass, loop-back (cycle +1) or test-case correction |
| Trigger | One or more rows fail or are confirmed failed at stage 8 (one job per failed row, plus one summary job per cycle) |
| Context | Failed row; rule rows it traces to; payload; response; checker/reviewer evidence; previous cycles' failures and fixes for this case; package version and hash |
| Tools | `get_test_row`, `get_rule_rows(case)`, `get_payload`, `get_response`, `get_cycle_history(case)`, `diff_package_versions(a, b)`, `resolve_sir` |
| Output | `{category: rule_config\|test_case\|payload\|package_gap\|environment\|unknown, root_cause, evidence[], proposed_fix: {target, change}, confidence}` plus a cycle summary grouping rows by root cause |
| Gate | Proposed fix target must exist (rule row, test row, field or package definition); category `rule_config` fixes are re-validated by the Other Logic grammar before display |
| Human | CCRE team chooses the action; a loop-back to stage 3 carries the accepted fixes as pre-filled edits |

**Steps**

1. Classify the failure: wrong rule, wrong test expectation, bad payload, missing package definition, or environment problem (timeouts, wrong endpoint, stale deployment).
2. Cite the evidence chain: test expectation → payload field → response element → rule row cell.
3. Check history: the same root cause in an earlier cycle is flagged as *repeat*.
4. Propose the smallest fix at the right place.
5. Summarise the cycle: N failures, K distinct root causes, recommended action.

**Measure:** UAT cycles per case (target trending to 1), human agreement with category, repeat failures.

**Eval cases:** wrong weight threshold in rule; wrong expected outcome in test row; package version mismatch (2.10.4 vs 2.10.9); CRMS TEST environment outage.

## Harness engineering

The harness is everything around the model: what it sees, what it may call, how its output is checked, how it is run, and how it is measured. In this app the harness, not the prompt, is what makes agents reliable, and much of it already exists as deterministic code.

| Harness layer | What it does | Already in the repo | To build |
| --- | --- | --- | --- |
| Context harness | Assembles exactly the inputs each agent needs, marks untrusted data, injects approved examples | Prompt files in `tools/agents/prompts/` | One context builder per agent; example retriever from approved rows |
| Tool harness | Read-only tools, per-agent allow-list, country scope, argument validation, call logging | Grammar, resolver, package and CRMS functions | Tool registry with allow-lists and logging |
| Validation harness | Turns every agent output into pass/fail with **machine-readable errors** the agent can repair from | 16-check validation register, condition grammar, sanity checks, `validate_plan`, UAT checker | Error format `{code, path, message, hint}` returned to the agent |
| Execution harness | Runs agents as jobs: timeout, retry budget, token budget, dead-letter, idempotency | Synchronous calls only | Job runner with budgets (main design, Phase 1) |
| Replay harness | Runs agents offline against recorded inputs and real model responses | `stub_llm.py` scripted responses | Record/replay of real Apigee runs on TEST |
| Evaluation harness | Scores agents on golden cases; gates prompt, model and tool changes | 25 agent tests on the stub | Golden sets per agent, scorers, CI release gate |
| Observability harness | Traces every run: context, tool calls, output, gate verdict, human decision | Template tracing component | Agent run log + trace per job |

Design rule: **every gate speaks to the agent.** A validator that only says "invalid" ends the run; one that says *which cell, which rule, what was expected* lets the agent repair itself in one retry. This is the cheapest reliability gain available, because the validators already exist.

## Feedback loops

Five loops run at different speeds: per run, per decision, per UAT cycle, per release of the checker, and per change to a prompt or model. Together they make the agents better with use instead of drifting.

[embedded content: feedback loops · 5 loops from seconds to releases]

| # | Loop | Speed | Signal in | What changes |
| --- | --- | --- | --- | --- |
| 1 | Self-repair | Seconds, inside one job | Structured gate error | The same suggestion, fixed once, else manual path |
| 2 | Human feedback | Each accept / edit / reject | Decision, cell-level diff, reason | Approved examples for few-shot; prompt rules for repeated edits |
| 3 | Outcome | Each sanity run and UAT cycle | Failures linked to the agent run that produced the item | New golden eval cases; weak spots per agent |
| 4 | Checker learning | Each release | `response_reviewer` hints confirmed by CCRE | New deterministic checker rules; AI share shrinks |
| 5 | Release gate | Each prompt, model or tool change | Eval harness scores vs last release | Ship, or block on regression |

Guardrail for loop 2: feedback changes examples and eval cases automatically, but prompt text changes only through a reviewed pull request that passes the eval gate. Agents never learn unsupervised in production.

## Where to leverage it

The biggest payoff is at `rule_drafter`, `test_case_designer` and `failure_analyst`, because their mistakes surface later as measurable downstream failures that can be traced back to a specific suggestion.

| Agent | Loop 1 · self-repair signal | Loop 2 · human signal | Loop 3 · downstream outcome | What the loop improves |
| --- | --- | --- | --- | --- |
| `rule_drafter` | Other Logic grammar errors, missing bindings, coverage gaps | Cells edited, rows discarded, reasons | Sanity failures, UAT failures traced to the row | Few-shot examples, prompt rules, new lint checks in the grammar |
| `requirement_interpreter` | Invalid SIR/SIRG, values not in workbook | Consultant rejection reasons | Gaps found later at sanity or UAT | Interpretation checklist, gap detection rules |
| `test_case_designer` | Uncovered branches, duplicate rows | Rows rejected or rewritten in two-stage review | Rule defects missed by UAT (found after RTP) | Branch templates per condition type |
| `payload_generator` | `validate_payload` errors | — | CRMS rejections | Field mapping hints, test-data pools |
| `response_reviewer` | Evidence paths that do not exist | CCRE disagreement with AI verdict | — | **New checker rules** (moves work from AI to code) |
| `failure_analyst` | Fix target does not exist | Category overridden by CCRE | Repeat failures in the next cycle | Root-cause playbook; checks added to sanity stage |
| `timeline_planner` | `validate_plan` violations | PM edits to dates | Actual vs planned milestone dates | Duration model per stage and country |
| `intake_assistant` | Pick-list and builder rejections | Fields the user changed before submit | Consultant rejections of the requirement | Clarifying-question order |
| `ccre_orchestrator` | Missing citations | Thumbs up / down | — | Routing and retrieval |

**Where in the code**

- `tools/agents/harness/` (new): `context.py`, `registry.py` (tool allow-lists), `runner.py` (repair loop, budgets), `errors.py` (shared error format).
- `tools/validation/`, `tools/core/` grammar, `tools/sanity.py`, `tools/timeline/`, `tools/execution/checker`: return the shared error format instead of booleans.
- `app` schema (new tables): `agent_run`, `agent_feedback` (human decision, edit diff, reason), `outcome_link` (sanity / UAT / CRMS result → agent run that produced the item).
- `evals/` (new): golden cases per agent, recorded responses, scorers, `make eval` in CI.

**First four steps**

- [ ] Make the 16-check register, the grammar and `validate_plan` return `{code, path, message, hint}`, and feed it into a single repair retry
- [ ] Store every human accept / edit / reject with the diff and reason in `agent_feedback`
- [ ] Link sanity, UAT and CRMS results back to the agent run that produced the row (`outcome_link`)
- [ ] Weekly job: turn the worst rejections and downstream failures into new eval cases, then rerun the eval gate

## Tool catalogue

All agent tools are read-only Python functions behind one registry; each agent is built with an explicit allow-list, and every call is logged with its arguments. Names below are proposed.

| Tool | Returns | Backed by | Agents allowed |
| --- | --- | --- | --- |
| `get_case` | Case summary, stage, country, approvals | `app` schema | Orchestrator, all |
| `get_intake_fields`, `get_picklist` | Required M2C columns, accepted values | Workbook / `sirdb` | intake\_assistant |
| `get_requirement_groups`, `get_requirement_bindings` | Groups and definitions in a package version | Active config package | intake\_assistant, rule\_drafter |
| `search_m2c_rows` | Live Import rows by country / SIR | `sirdb.v_import_final` | interpreter, rule\_drafter, orchestrator |
| `resolve_sir` | SIR/SIRG resolution and references | `sirdb` resolver | interpreter, rule\_drafter, failure\_analyst, orchestrator |
| `get_package_definition`, `package_coverage`, `diff_package_versions` | Definitions, coverage gaps, version diffs | Package store | interpreter, rule\_drafter, failure\_analyst |
| `check_condition`, `check_other_logic`, `explain_condition` | Grammar verdict, errors, branches | Condition grammar | intake\_assistant, rule\_drafter, test\_case\_designer |
| `diff_against_workbook` | Cell-level changes | Rule-config engine | rule\_drafter |
| `get_baseline_plan`, `get_calendar`, `get_historical_stage_durations`, `validate_plan` | Plan baseline, blackouts, history, verdict | Timeline module, audit trail | timeline\_planner |
| `get_rule_rows`, `get_test_row`, `get_existing_test_rows` | Accepted rules and UAT rows | `app` schema | test\_case\_designer, reviewer, failure\_analyst |
| `get_crms_fields`, `get_sample_payload`, `build_payload`, `validate_payload` | Catalogue, template, built message, verdict | `crms.py` | payload\_generator, test\_case\_designer |
| `get_payload`, `get_response`, `compare_envs`, `get_cycle_history` | Evidence for a run | Object storage + `app` | reviewer, failure\_analyst, orchestrator |
| `get_audit_history` | Decisions with actor and reason | Audit table | orchestrator |

Tools enforce the user's country scope themselves (the job carries the requesting user's scope), so a prompt cannot widen access.

## Context, prompts and versioning

Agents get small, assembled context per call rather than long chat history, which keeps results reproducible and cost predictable.

- **Context builder per agent:** a code function assembles exactly the inputs listed in each card, in a fixed order, with clear delimiters for untrusted data (`<business_text>`, `<workbook_rows>`, `<crms_response>`).
- **No cross-case memory.** Each run starts clean; learning from the past comes only through tools (similar rows, cycle history, approved examples).
- **Few-shot from approved data:** examples are pulled at run time from human-approved rows/test cases of the same SIR type, so prompts improve as the system is used.
- **Prompt files versioned in Git** (`tools/agents/prompts/*.md`) with a version header; the version is written to the agent run log and shown in the UI tooltip of each suggestion.
- **Model settings pinned per agent:** model ID, temperature (0 for rule\_drafter, payload\_generator, response\_reviewer; low for others), max tokens, timeout. Changing any of them is a reviewed change that reruns the evaluation set.
- **Stub parity:** `stub_llm.py` scripts stay for unit tests, plus recorded real responses (record/replay) for realistic regression tests.

## Evaluation and monitoring

Each agent has an offline evaluation set that gates releases and live metrics that show drift; the risk tier decides how strict both are.

| Agent | Risk tier | Offline release gate (proposal) | Key live metric |
| --- | --- | --- | --- |
| `rule_drafter` | High | 100% grammar-valid; no invented definition IDs; ≥ 90% rows match approved reference rows | Sanity first-pass rate |
| `requirement_interpreter` | High | Correct SIR/SIRG on all eval cases; all known package gaps flagged | Consultant approval without edit |
| `failure_analyst` | Medium | Correct category on ≥ 85% of labelled failures | UAT cycles per case |
| `test_case_designer` | Medium | 100% branch coverage on eval rules | Rows rejected in review |
| `payload_generator` | Medium | 100% payload validation pass | CRMS rejections |
| `response_reviewer` | Medium | Agreement with human labels ≥ 90% | Undecided rate trend |
| `timeline_planner` | Low | 100% `validate_plan` pass | PM edits per plan |
| `intake_assistant` | Low | ≥ 90% fields correct on eval texts | Questions per form |
| `ccre_orchestrator` | Low | Citation present in 100% of answers | Helpful ratio |

**Every run logs:** agent, prompt version, model, latency, tokens, cost, tool calls, schema-valid, gate result, human decision, edit distance. These feed one "Agent quality" dashboard and alerts on schema-invalid spikes, latency SLO breaches and cost per case above budget.

Thresholds are starting proposals; set the real ones after the Phase 2 live run.

## Build checklist for the agent layer

Ordered so each step is useful on its own; steps 1–5 fit Phase 1, steps 6–9 fit Phase 2 of the main plan.

- [ ] 1\. Define the common output envelope and one Pydantic schema per agent in `tools/agents/schemas`
- [ ] 2\. Build the tool registry with per-agent allow-lists and country-scope enforcement inside each tool
- [ ] 3\. Write a context builder per agent; mark untrusted data with delimiters
- [ ] 4\. Run every agent as a worker job with timeout, one validation-feedback retry and dead-letter state
- [ ] 5\. Add the agent run log table and write every run to it
- [ ] 6\. Build evaluation sets, starting with `rule_drafter` and `requirement_interpreter` (DE POA, BG IOSS)
- [ ] 7\. Record real Apigee responses on TEST for replay tests
- [ ] 8\. Pin model settings per agent; add the eval run to CI as a release gate
- [ ] 9\. Add the Agent quality dashboard and alerts
- [ ] 10\. Turn `response_reviewer` hints into checker rules every release
