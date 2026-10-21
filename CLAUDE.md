# CCRE Onboarding Agent — rules for Claude Code

## What this is
Google ADK app (Python 3.11+, FastAPI, SQLAlchemy, vanilla JS SPA) that takes a country's customs
requirement from business intake to RTP in CCRE through a 9-stage, 15-state lifecycle
(`tools/workflow/state_machine.py`). 8 specialist agents + root `ccre_orchestrator` (`agent.py`).
Design docs: `docs/design/production-design.md`, `docs/design/agent-design.md`,
`docs/design/*.mmd`. Read the relevant section before changing anything.

## Non-negotiable principle
Agents recommend, code validates, humans approve.
- No agent gets a tool that writes case state, approves, sends email, uploads, or calls CCRE/CRMS
  to change anything. Agent tools are read-only.
- Case state changes only through the single transition service, inside one DB transaction,
  with an audit row.
- Every agent output is stored as a draft and must pass deterministic gates before a human sees it.
- Every stage must remain completable manually when agents are unavailable.

## Engineering rules
- Keep all existing tests green. Run `pytest -q` before and after every change. Never delete or
  weaken a test to make it pass; if a test is wrong, explain why and ask.
- Tests use the stub LLM (`components/llm/stub_llm.py`) and mock CCRE. Never call Apigee, CRMS or
  CCRE from tests. No network in tests.
- Add tests for every new module: happy path, failure path, and the guardrail it enforces.
- Small, reviewable commits. One phase = one branch = one PR. Branch name given in each phase.
- Do not change public API routes or UI behaviour unless the phase says so.
- Type hints on all new code. Pydantic models for every agent input/output and every error.
- No secrets in code, logs, fixtures or commits. `.env`, `secret.key`, `.ccre_data/` stay ignored.
- Do not push, force-push, delete branches, or run destructive git commands without asking me first.
- Prefer extending existing modules (`tools/validation/`, `tools/core/`, `tools/execution/`,
  `tools/agents/`) over creating parallel ones. Search before you create.
- When something in the design doc conflicts with the code, stop and tell me; do not guess.

## Definition of done for any phase
1. Acceptance criteria in the phase prompt all pass.
2. `pytest -q` fully green; new tests added; test count reported before/after.
3. Docs updated (README, `docs/`, and an ADR in `docs/adr/` for any design decision).
4. A short report: what changed, files touched, what was deferred, risks, next step.
