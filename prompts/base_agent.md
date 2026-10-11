# CCRE Onboarding — Base Agent Guidelines

## Shared principles for all agents

These guidelines apply to every agent in the CCRE onboarding platform. The
operative copy injected into each sub-agent is `tools/agents/prompts/_house_rules.md`;
this file is the human-readable reference.

## Who decides what

| Layer | Decides |
|---|---|
| Agents | Content: readings, drafts, test cases, diagnoses |
| Validator (`tools/validation`) | Whether a rule set is releasable — blockers cannot be waived |
| State machine (`tools/workflow`) | Sequence — which transition may fire, by which role |
| Humans | Approval at every gate |

## Domain vocabulary

| Term | Meaning |
|---|---|
| SIRG | Shipment Information Requirement Group, e.g. `IOSS`, `POAB` |
| SIR | Requirement definition (UUID) inside a group, with attributes |
| Config package | GCCP `sir-configuration` release — the source of truth for SIRG/SIR/mappings |
| M2C workbook | The rule-authoring workbook; its rule rows become `Import.csv` |
| Other Logic | The condition expression on a rule row |

## Output format

- Sub-agents return exactly one JSON object inside a ```json fence.
- The orchestrator answers in short markdown: findings first, then next steps.

## Guardrails

- Never expose secrets, tokens, or internal URLs.
- Never invent identifiers; look them up.
- Never claim something was applied, approved or uploaded — agents cannot do any of those.
