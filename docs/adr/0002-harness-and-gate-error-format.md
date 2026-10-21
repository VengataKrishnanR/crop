# ADR 0002 — Agent harness and the shared gate error format

- Status: Accepted
- Date: 21-10-2026
- Context documents: `docs/design/agent-design.md` ("The agent contract", "Harness engineering",
  "Tool catalogue"); ADR 0001

## Context

Every agent output must pass a deterministic gate before a human sees it (ADR 0001). The gates
already existed (Other Logic grammar, 16-check register, plan validation, UAT checker), but each
spoke its own format: `Diagnostic` lists, `Finding` objects, a raised `ValueError`, a dict with
`conclusive`. An agent cannot repair its output from "invalid"; it can from *which field, which
rule, what was expected*. Agent tools were plain ADK `FunctionTool` lists per agent, with the
read-only property held by convention and tests, and no country scope.

## Decision

1. **One error format.** `tools/agents/harness/errors.py`:
   `GateError {code, path, message, hint?, severity: error|warning}` and
   `GateResult {passed, errors[]}`. `passed` is false only when an `error` is present; warnings
   are shown to the human but never block.
2. **Adapters, not rewrites.** Each existing validator keeps its old return type and callers; a
   `gate_*` adapter returns `GateResult`:

   | Validator | Adapter | Path convention |
   |---|---|---|
   | Other Logic grammar | `tools.core.grammar.gate_other_logic(expr, path)` | caller's path; parse errors append `@<char position>` |
   | 16-check register | `tools.validation.gate_findings(report)` | rule-level checks: `rules[<rule id>].<field>`, one error per rule; others: the finding's `where` |
   | Plan validation | `tools.timeline.gate_plan(milestones, answers)` | `milestones[i].<start\|end\|stage>` |
   | CRMS payload | `tools.execution.crms.validate_crms_payload(payload, country, direction)` (new) | dotted message path, e.g. `ShpPcdDetailsMsg.Bd.Shp[0].MonAmt[0].Amt[0].@CurCd` |
   | UAT checker | `tools.execution.checker.gate_check(result)` | the response paths that could not be read, else `response` |

   Severity mapping for the register: blocker → error, caution → warning, info → dropped.
3. **UAT checker outcome.** `check_response` results now carry `outcome: pass|fail|undecided` and
   a `reason_code` (`AS_EXPECTED`, `EXPECTED_NOT_RAISED`, `UNEXPECTED_RAISED`, `CASE_FLAG_MISMATCH`,
   `HTTP_ERROR`, `NO_RESPONSE`, `SERVICE_STATUS_NOT_OK`, `PATH_NOT_FOUND`). Existing keys
   (`conclusive`, `passed`, `reasons`) are unchanged. `undecided` is never a pass; it is the only
   outcome that routes to `response_reviewer`.
4. **Plan gate enforces weekends and blackouts.** The design requires "no weekend or blackout
   dates"; `validate_plan` never checked it. `gate_plan` does (`PLAN_NON_WORKING_DAY`, with the next
   working day as the hint). `validate_plan` and the live timeline path are unchanged until the
   runner (Phase 3) and the `timeline_planner` card work (Phase 4) switch to the gate. "At risk" is
   computed by code as a warning (`PLAN_AT_RISK`).
5. **Output envelope.** `AgentOutput[T] {suggestion, rationale, assumptions, open_questions,
   confidence 0..1, sources[SourceRef]}`; `SourceRef.kind` is one of `requirement_field`,
   `m2c_row`, `package_definition`, `calendar`, `crms_field`, `crms_response`, `audit_event`.
6. **Tool registry** (`tools/agents/harness/registry.py`):
   - registration refuses `read_only=False`, unknown agent names, empty allow-lists, and tools that
     do not declare exactly one country rule (`country_arg`, `country_resolver`, `country_neutral`);
   - `get_tools_for(agent)` returns only allowed tools; `call()` refuses others;
   - every call carries a `CallScope` (user id, role, countries). Internal roles see every country,
     business users only their own — the same rule as `tools.core.security.can_see_country`. A
     country outside scope (or an unresolvable one, e.g. an unknown case id) raises `ScopeError`
     before the tool runs;
   - every call is logged (tool, agent, args hash, duration, ok/error) and kept in `registry.calls`
     for the run log (Phase 3).
7. **Catalogue.** `tools/agents/harness/catalogue.py` registers 18 of the 30 design tools against
   existing functions, with the design table's allow-lists. The other 12 are listed in
   `CATALOGUE_GAPS` with the phase expected to add them; a test keeps the two in step with the table.
   Country-neutral tools are pure functions over their arguments (grammar, plan gate, payload
   build/validate/compare) or package-catalogue reference data (`get_package_definition`).
8. **Context builder.** `ContextBuilder` subclasses declare `SECTIONS`; output follows that order
   and refuses undeclared sections. `wrap_untrusted` puts business text, workbook rows and CRMS
   responses inside `<business_text>`, `<workbook_rows>`, `<crms_response>` and escapes any of those
   tags inside the data, so injected text cannot close its block.

## Consequences

- No agent behaviour changes in Phase 1: agents keep their ADK tool lists; nothing in the request
  path calls the adapters yet. Phases 3–4 route agents through the registry and the gates.
- Hints are part of the contract: a new check or diagnostic code should come with a hint.
- Known differences between the design's agent cards and its Tool catalogue table, resolved in
  favour of the table for now and to be settled per agent in Phase 4:
  `requirement_interpreter` lists `check_condition` and `find_similar_requirements` in its card but
  not in the table; `ccre_orchestrator` lists `get_package_definition` and `get_uat_results`.
- `search_m2c_rows` and `package_coverage` read the app's rule/package tables until Phase 2 moves
  reference reads to sirdb; `resolve_sir` already reads sirdb and needs PostgreSQL.

## Rejected alternatives

- **Rewrite validators to return `GateResult` directly.** Would change every caller and the UI in a
  phase that must not change behaviour.
- **Scope enforcement in prompts.** A prompt cannot be trusted to keep a business user's agent out
  of another country's data; the registry checks it in code.
