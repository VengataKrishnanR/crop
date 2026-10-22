# ADR 0001 — Agents recommend, code validates, humans approve

- Status: Accepted
- Date: 21-10-2026
- Context documents: `docs/design/production-design.md` (Executive summary, Current-state assessment),
  `docs/design/agent-design.md` (The agent contract)

## Context

The platform uses 8 specialist LLM agents and a root `ccre_orchestrator` to help take a country's
customs requirement from intake to RTP in CCRE. The output ends up as production customs rules
(M2C Import rows) and as calls into CRMS/CCRE. An LLM can be wrong, slow, unavailable, or
steered by untrusted text (business free text, workbook cells, CRMS responses).

The codebase already separates these roles in practice: deterministic validators (16-check
validation register, condition / Other Logic grammar, 6 sanity checks, package checks, plan
validation, UAT checker) and role-based human approvals through the 15-state lifecycle in
`tools/workflow/state_machine.py`. This ADR records that separation as an architectural rule so
later work (harness, job runner, feedback loops) cannot erode it.

## Decision

1. **Agents recommend.** An agent is a suggestion function: it reads context through read-only
   tools and returns one typed suggestion. No agent has a tool that writes case state, approves or
   rejects, sends email, uploads files, or calls CCRE/CRMS to change anything. Only the
   orchestrator delegates, and only in explain mode for Ask Expert.
2. **Code validates.** Every agent output is stored as a draft and passes deterministic gates
   (schema, grammar, validation register, coverage, checker) before a human sees it. Values the
   design marks "computed by code" (conflicts, coverage, diff, at-risk) are computed by code and
   override the agent. A failed gate gets at most one repair retry, then the manual path.
3. **Humans approve.** Only the stage's approving role can accept a suggestion. Acceptance is a
   lifecycle transition through the single transition service, in one DB transaction, with an
   audit row (actor, role, before/after, reason).
4. **Manual path always works.** Every stage can be completed by hand when agents are down,
   slow, or wrong.

## Consequences

- New agent tools must be registered as read-only; a tool registry will enforce this (Phase 1).
- Reviews of any change check for agent write paths and for state changes outside the transition
  service; either is a blocking defect.
- Some work stays manual that an agent could technically do (e.g. auto-submitting a filled form,
  auto-applying a fix). That cost is accepted in exchange for auditability and safety.
- Stages 4 (sanity check) and 9 (RTP) stay fully deterministic, with no agent.

## Rejected alternatives

- **Agents with write tools behind a confirmation prompt.** Puts the safety boundary inside the
  prompt/UI rather than in code; one prompt injection or UI bug bypasses it.
- **Auto-apply high-confidence suggestions.** LLM confidence is not calibrated against customs
  correctness; a wrong production rule costs far more than a human click.
