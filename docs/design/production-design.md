# CCRE Onboarding Agent — Production System Design

Oct 21, 2026 · @VengataKrishnanR

> Exported from the Claude Doc "CCRE Onboarding Agent — Production System Design"
> (https://claude.ai/artifact/C6fbzc4E6ym53JbwuMNwM9), tab "CCRE Onboarding Agent — Production System Design", rev 15.
> The two embedded diagrams (target architecture, roadmap) are not included in the Markdown export.

## Executive summary

The application is functionally rich and test-green (260/260), but operationally it is still a single-machine prototype: SQLite, local secrets, a default admin, no deployment target, and 11 commits of unpushed work in OneDrive. It has never run against the real LLM or real CRMS/CCRE endpoints. The path to enterprise grade is hardening, not new features.

The five decisions that matter most:

1. **Secure the code today.** Push every branch, fast-forward `main` to `timeline-pm`, move the repo out of OneDrive, protect `main`.
2. **One database: PostgreSQL.** The app schema and `sirdb` live side by side in one cluster; `sirdb` becomes the single source of truth for reference data; SQLite is retired.
3. **Split web from work.** A stateless API tier plus a background worker tier for LLM calls, UAT execution, package review and email, connected by a durable job queue.
4. **Enterprise identity and secrets.** Corporate SSO (OIDC) with group-to-role mapping, secrets in a vault, the default admin removed.
5. **Prove it live before anyone relies on it.** A gated end-to-end run with Apigee LLM and CRMS TEST/UAT, with recorded evidence, before the first pilot country.

Guiding principle stays unchanged and becomes an architectural rule: *agents recommend, code validates, humans approve* — no agent gets a write path to case state, approvals or CCRE.

## Current-state assessment

The domain design is the strongest asset; the runtime and operations layer is the weakest. Keep the first, rebuild the second.

**Strengths to keep**

- Clear separation of agents (recommend) from deterministic code (validate) and humans (approve).
- Explicit 15-state lifecycle in `tools/workflow/state_machine.py` with gate facts per case.
- Deterministic checks first (16-check register, 6 sanity checks, ~11 package checks), AI only as fallback.
- Audit trail already drives KPIs; approvals carry reasons everywhere.
- `sirdb` round-trip proven: export equals the workbook Import sheet with 0 cell differences.
- Pluggable LLM gateway (Apigee / stub / OpenAI / Google AI) inherited from the ADK template.

**Production gaps**

| Area | Today | Production risk | Severity |
| --- | --- | --- | --- |
| Source control | 4 branches unpushed, repo in OneDrive | Total loss of latest work; `.git` sync corruption | Critical |
| Database | SQLite file, no app migrations | No concurrency, no HA, no safe schema change | Critical |
| Identity | Local users, default `admin@ccre.local` | Unauthorised access; fails InfoSec review | Critical |
| Secrets | `.env` and `secret.key` on disk | Key leak; no rotation | Critical |
| Real integrations | Only stub LLM and mock CCRE tested | Unknown behaviour on Apigee latency, errors, real payloads | High |
| Execution model | LLM and UAT calls inside web requests (assumed) | Timeouts, lost work on restart | High |
| Two reference stores | SQLite ingestion and `sirdb` both read the workbook | Divergent truth for rule config | High |
| Hosting / CI | `START.bat`, `scripts/ci.sh` only | No repeatable deploy, no rollback | High |
| Files | `.ccre_data/` local (outbox, uploads, evidence) | Lost on host change; no scaling | Medium |
| Observability | Template logging/tracing, no dashboards or alerts | Failures found by users | Medium |
| Maintainability | `ui/app.js` 2,158 lines, `server/lifecycle.py` 935 | Slower, riskier change | Medium |
| Docs | Timeline ownership and branch names drifted | Wrong mental model for reviewers | Low |

One assumption to confirm: whether LLM and UAT calls currently run synchronously in request handlers. The rest of this design assumes they do.

## Target architecture

The API only validates, authorises and records; everything slow or external runs in workers, and all state lives in PostgreSQL and object storage, so any container can be replaced at any time.

[embedded content: target architecture · 4 tiers plus platform services]

Read top to bottom: a request enters through SSO and the ingress, the API writes state and enqueues a job, and a worker calls Apigee, CRMS/CCRE or SMTP and writes the result back.

| Component | Responsibility | Must never |
| --- | --- | --- |
| Web UI | Render stages, forms, review grids; call the API | Hold business rules or secrets |
| API service | Authenticate, authorise (role + country), validate, run state transitions with audit, enqueue jobs, serve downloads | Call the LLM or CRMS inline |
| Worker service | Run the 8 agents and orchestrator, UAT execution and checker, sanity runs, package review, email outbox | Change case state except through the same transition service |
| PostgreSQL | `app` and `sirdb` schemas, job queue, outbox, audit | Be written to outside migrations and the app roles |
| Object storage | Uploaded and generated files, write-once | Be the only record of what a file means (metadata lives in Postgres) |
| Integrations | Apigee (LLM), CRMS/CCRE TEST and UAT, SMTP | Be reached without timeout, retry policy and circuit breaker |

## Key design decisions

Each answers one of the seven planner questions; the recommendation is the default unless a DHL platform constraint says otherwise.

| # | Decision | Recommendation | Why | Rejected alternative |
| --- | --- | --- | --- | --- |
| 1 | Branch consolidation | Push all branches now. Tag `main` as `v3`, open a PR `timeline-pm → main`, review, fast-forward merge (no squash). Delete `v2-lifecycle` and `crms-execution`. Move to trunk-based work with short branches and protected `main` | Pushing removes the loss risk in minutes. The 15 commits are meaningful units; squashing destroys reviewable history of the 8.7k-line `sirdb` change | Squash to one commit; keep stacking branches |
| 2 | Reference data source | `sirdb` becomes the single source of truth. Rule config, intake pick-lists and sanity checks read reference data through one repository interface backed by `sirdb.v_import_final`. The app's own workbook ingestion is retired | Two parsers of one workbook will drift. `sirdb` already has migrations, a loader, a resolver and a 0-difference round-trip | Keep SQLite ingestion plus a separate analysis DB |
| 3 | App database | PostgreSQL 16, one cluster, two schemas: `app` (cases, users, audit, jobs) and `sirdb` (reference). Alembic for `app`; keep the `sirdb` SQL migrations but run both from one migrator at deploy time | Concurrency, HA, PITR backups, one backup/restore story | SQLite in production; two separate databases |
| 4 | Execution model | API tier stays thin and stateless. LLM agent runs, UAT execution, package review, sanity runs and email go to a worker tier via a durable job queue (Postgres-backed queue first; Redis-based only if throughput demands it) | Long calls must survive restarts and timeouts; retries need a home | Background threads in the web process |
| 5 | Identity | OIDC SSO with the corporate IdP; IdP groups map to ADMIN / PM / CCRE\_CONSULTANT / CCRE\_TEAM / BUSINESS; country scope from group or admin mapping. Local accounts only as audited break-glass | Joiner/leaver handled by the company; passes InfoSec | Local user store with passwords |
| 6 | Files | Uploads (beta packages, workbooks), UAT evidence, exports and outbox go to object storage with SHA-256 keys; metadata in Postgres | Stateless app nodes; durable, scannable files | `.ccre_data/` on local disk |
| 7 | Next functional scope | Harden the Import-tab flow first; extend M2C (SIR Reference, Export, Technical sheets) only after the first pilot country reaches RTP | Every extension multiplies the untested surface | Extend scope now |
| 8 | Frontend | Keep vanilla JS; split `app.js` into ES modules per lifecycle stage behind a small build step (e.g. Vite). Revisit a framework only if the UI keeps growing | A rewrite adds risk with no user value | Rewrite in React now |

Record each decision as a short ADR in `docs/adr/` so reviewers see the reasoning, not just the result.

## Reliability and resilience

The goal: no approval is ever lost or doubled, and an outage of the LLM or CRMS never blocks a human from moving a case forward manually.

**State integrity**

- Every lifecycle transition runs in one DB transaction: check gate facts → update case → write audit row. No transition without its audit row.
- Optimistic locking: a `version` column on cases, rule-config drafts and test-case rows; a stale approve returns 409, not a silent overwrite.
- Idempotency keys on approve/reject, beta-file upload, "send DMG email" and "run UAT" so a double click or retry has one effect.
- Transactional outbox for email and notifications: write the message row in the same transaction, a worker sends it. Fixes "approved but email never went" and vice versa.

**External calls (Apigee LLM, CRMS / CCRE endpoints, SMTP)**

- Explicit connect and read timeouts on every client; no unbounded waits.
- Retries with exponential backoff and jitter only for safe cases (timeouts, 429, 5xx); never retry a non-idempotent CCRE call blindly.
- Circuit breaker per dependency; when open, the UI shows "AI assist unavailable" and the manual path stays usable.
- Bulkheads: separate worker queues for LLM, UAT execution and email so a slow CRMS does not starve agent runs.

**Runtime**

- At least 2 API replicas and 2 workers behind a load balancer; `/healthz` (liveness) and `/readyz` (DB, queue, vault reachable).
- Graceful shutdown: workers finish or release in-flight jobs; jobs carry attempt count, last error and a dead-letter state visible to admins.
- Rate limits per user on AI endpoints ("Ask Expert", NLP fill) to protect the LLM budget.

**Recovery targets (proposals to agree with the business)**

| Target | Proposal | How |
| --- | --- | --- |
| RPO | 15 minutes | Postgres point-in-time recovery, object storage versioning |
| RTO | 4 hours | Infra as code, image redeploy, documented restore runbook |
| Restore drill | Quarterly | Restore to a scratch environment and run the smoke suite |

## Security and compliance

The app handles customs rules and shipment payloads and can trigger calls into CCRE/CRMS, so it should be designed to pass a DHL InfoSec review before the first pilot, not after.

| Control area | Action |
| --- | --- |
| Authentication | OIDC SSO; MFA enforced by the IdP; session cookies `HttpOnly`, `Secure`, `SameSite=Lax`; short session lifetime |
| Authorisation | RBAC plus country scope enforced in one server-side policy layer, never in the UI; a test per role × endpoint matrix; four-eyes rules (e.g. DMG approve-and-send) checked in code |
| Secrets | Apigee key, CRMS/CCRE endpoint keys, DB credentials and the encryption key in a vault; loaded at start-up; rotation runbook; remove `secret.key` and `.env` from hosts |
| Encryption | TLS everywhere including to Postgres; encryption at rest for DB and object storage; envelope encryption for stored endpoint keys |
| File uploads | Size limits; zip-slip and zip-bomb protection on `sir-configuration` packages; content-type checks; malware scan before activation |
| Web hardening | CSRF tokens, CSP headers, strict CORS, input validation via Pydantic models, no raw SQL string building |
| Supply chain | Pinned dependencies with hashes; `pip-audit`, SAST (`bandit`/Semgrep), secret scanning (gitleaks), container image scan (Trivy) in CI; SBOM per release |
| LLM-specific | Treat business free text as untrusted input to agents; agents keep zero write tools; validate every agent output against its schema; redact PII before logging prompts |
| Audit | Append-only audit table (no UPDATE/DELETE grants for the app role); actor, role, country, before/after, reason, timestamp; retention agreed with compliance |
| Assurance | Data classification sign-off, threat model per stage, penetration test before go-live |

## Data architecture

One PostgreSQL cluster with two schemas, files in object storage, and every schema change shipped as a versioned migration.

| Store | Holds | Owner | Change mechanism |
| --- | --- | --- | --- |
| `app` schema | Users/roles mapping, cases, lifecycle state, timeline, rule-config drafts, sanity runs, exceptions, UAT rows and results, approvals, audit, jobs, outbox, endpoint config | This application | Alembic migrations, run once per deploy before new pods start |
| `sirdb` schema | Workbook-derived SIR/SIRG reference, `v_import_final`, package mappings | CCRE reference data | Existing SQL migrations 0001–0005, same deploy step |
| Object storage | Workbooks, beta zips (keyed by SHA-256), UAT evidence zips, M2C exports, sanity `.xlsx` reports | This application | Write-once, versioned bucket |

**Rules**

- Cases reference reference data by **package version + hash**, so a case is always reproducible against the package it was configured on.
- Workbook and package loads are idempotent and versioned; a new beta (e.g. `2.10.9-beta.2`) loads beside the old one, activation is a pointer switch.
- Migrations are backward compatible for one release (expand → migrate → contract) so a rollback of the app does not need a DB rollback.
- Tests run against real PostgreSQL (Testcontainers) to remove SQLite/Postgres dialect drift.
- Retention (proposal): audit trail and approvals kept for the life of the rule plus the compliance period; UAT evidence 2 years; outbox messages 90 days. Confirm with compliance.
- Backups: PITR with 7–35 day window, nightly logical dump to a separate account, quarterly restore drill.

## Observability

Every request, job and external call should be traceable by one case ID, so support can answer "what happened to case X" in minutes.

- **Logs:** structured JSON; fields `request_id`, `case_id`, `country`, `stage`, `user_role`, `job_id`, `agent`; shipped to the company log platform (e.g. Splunk). No secrets or raw PII.
- **Traces:** OpenTelemetry spans across API → queue → worker → Apigee / CRMS / CCRE, reusing the template's tracing component.
- **Metrics:** HTTP latency and error rate per route; queue depth and job age per queue; job failures and dead letters; LLM latency, tokens, cost, schema-invalid rate per agent; UAT executor pass/fail/error per endpoint; email send failures.
- **Business KPIs:** keep the audit-derived KPIs (lead time, on-time %, first-time-right, UAT cycles) and publish them to a dashboard.

**Proposed SLOs (to agree with the business)**

| SLO | Target |
| --- | --- |
| API availability, business hours | 99.5% |
| p95 latency, interactive API calls | < 1 s |
| p95 agent job completion | < 60 s |
| Email delivered after approval | < 5 min |

**Alerts** page only on SLO burn, dead letters, circuit breakers open > 15 minutes, failed backups and certificate expiry; everything else goes to a dashboard.

## CI/CD, environments and release

One immutable container image per commit, promoted unchanged through four environments; only configuration differs.

**Pipeline on every PR**

1. Lint and format (`ruff`), type check (`mypy` on `tools/` and `server/` first).
2. Unit tests with the stub LLM (today's 260).
3. Integration tests on PostgreSQL via Testcontainers, including Alembic upgrade from the previous release.
4. Security: `pip-audit`, Semgrep/`bandit`, gitleaks.
5. Build image, scan with Trivy, generate SBOM, push to the registry.

**Environments**

| Env | Purpose | LLM / endpoints | Deploy |
| --- | --- | --- | --- |
| DEV | Integration of merged work | Stub + mock CCRE | Automatic on merge to `main` |
| TEST | Real-integration testing | Apigee + CRMS TEST | Automatic, plus nightly live smoke run |
| UAT | Business acceptance of the app itself | Apigee + CRMS UAT | Manual approval |
| PROD | Live use | Apigee + production-approved endpoints | Change ticket (ServiceNow), approval, blue/green or rolling |

**Release rules**

- Infra as code (Terraform/Helm, whichever the DHL platform standard is) for app, DB, storage, secrets and DNS.
- 12-factor configuration via typed settings (`pydantic-settings`); the app refuses to start in PROD with `LLM_MODE=stub`, default credentials or a missing vault.
- Rollback = redeploy the previous image; migrations are expand/contract so this is always safe.
- Contract tests for the CRMS `ShpPcdDetailsMsg` mapping using recorded real responses.

## AI / LLM governance and evaluation

The stub proves the plumbing; it says nothing about answer quality. Production needs a measured, versioned AI layer.

- **Golden evaluation set:** real cases per agent (e.g. DE POA, BG IOSS) with expected outputs; run on every prompt or model change; block release on regression.
- **Record and replay:** capture real Apigee responses from TEST runs as fixtures, so offline tests use realistic outputs, not only scripted stubs.
- **Versioning in the audit trail:** each agent suggestion stores agent name, prompt version, model ID, input hash and output, so any recommendation can be explained later.
- **Output safety:** schema validation on every response; one retry with the validation error; then hand over to the manual path. Never auto-apply.
- **Cost and load control:** token budget per case and per user per day; caching of identical requests (e.g. requirement interpretation of unchanged text).
- **Quality metrics in production:** schema-valid rate, human acceptance rate of suggestions, edit rate before approval, first-time-right of AI-drafted rules versus manual.

## Code health and modularisation

Split the two large files now, right after the merge and before the Postgres work, while 260 green tests protect the refactor.

- **Backend layering:** `server/` routes become thin (parse, authorise, call a service); domain logic moves into per-stage service modules (`services/intake.py`, `timeline.py`, `ruleconfig.py`, `sanity.py`, `uat.py`, `rtp.py`); data access behind repository classes, so the SQLite → Postgres and `sirdb` switch touches one layer.
- **`server/lifecycle.py` (935 lines):** split by stage into routers that share the state machine; transitions only through one `transition(case, event, actor)` function.
- **`ui/app.js` (2,158 lines):** ES modules per stage plus shared `api.js`, `auth.js`, `components/`; add a build step; add a handful of Playwright UI tests for the critical paths (submit requirement, approve, run UAT, sign off).
- **Housekeeping:** fix the Starlette `httpx` TestClient warning, delete `tests/__pycache__` debug bytecode, add `.gitignore` rules for `.ccre_data/`, `.env`, `secret.key`.
- **Docs drift:** update README "Who submits" and the lifecycle diagram to PM-owned timeline; fix the branch reference in `docs/rule-configuration.md`; add ADRs and an operations runbook.

## Prioritised action plan

Follow your suggested order with one change: real-environment validation comes after the Postgres and job-queue foundations, so the live run tests the architecture you will actually ship.

[embedded content: roadmap · 6 phases, 5 gates]

Each phase starts only when its gate is met; durations below are rough single-developer estimates to refine.

### Phase 0 — Secure the work (this week)

- [ ] Push `sanity-guided`, `sir-reference-db`, `timeline-pm` and every other branch to origin
- [ ] Tag current `main` as `v3`; open PR `timeline-pm → main`; review; fast-forward merge
- [ ] Delete `v2-lifecycle` and `crms-execution` locally and on origin
- [ ] Re-clone outside OneDrive; enable branch protection (PR + green CI required)
- [ ] Confirm `.env`, `secret.key`, `.ccre_data/` are git-ignored and never committed
- [ ] Fix doc drift: README timeline ownership, lifecycle diagram, branch reference in `docs/rule-configuration.md`
- [ ] Send the business and platform requests listed under dependencies

### Phase 1 — Foundations (estimate 2–3 weeks)

- [ ] CI pipeline: lint, type check, tests, security scans, image build
- [ ] Split `server/lifecycle.py` and `ui/app.js`; add service and repository layers
- [ ] App DB on PostgreSQL with Alembic; tests on Testcontainers
- [ ] Replace the app's workbook ingestion with the `sirdb` repository; cases pin package version and hash
- [ ] Job queue and worker for LLM, UAT execution, package review and email; transactional outbox
- [ ] Optimistic locking and idempotency keys on approvals, uploads and UAT runs
- [ ] Typed settings; refuse PROD start with stub LLM or default credentials

### Phase 2 — Real-environment validation (estimate 1–2 weeks)

What to prove: one case (DE POA, or BG IOSS once the newer package arrives) from intake to RTP export using Apigee and CRMS TEST.

- [ ] All 8 agents return schema-valid output on real Apigee; responses recorded as fixtures
- [ ] CRMS TEST accepts generated payloads; deterministic checker agrees with expected results
- [ ] Measure agent latency p50/p95, tokens and cost per case, schema-invalid rate, CRMS error rate, end-to-end time
- [ ] Failure drills: Apigee timeout, CRMS 5xx, worker killed mid-job; no lost or doubled state
- [ ] Build the golden evaluation set from these runs
- [ ] Assemble an evidence pack (logs, traces, evidence zips) for reviewers

### Phase 3 — Production hardening (estimate 3–4 weeks)

- [ ] OIDC SSO with group-to-role mapping; remove default admin; audited break-glass account
- [ ] Secrets in a vault; rotation runbook
- [ ] Object storage for files; upload scanning and zip safety
- [ ] IaC and container deploy to DEV/TEST/UAT/PROD; probes; at least 2 replicas per tier
- [ ] Logs to the company platform, OpenTelemetry traces, dashboards, SLO alerts
- [ ] PITR backups, restore drill, retention jobs
- [ ] Threat model, pen test, InfoSec sign-off; operations runbook and support model

### Phase 4 — Pilot country

- [ ] One country with named users per role takes a real requirement to RTP
- [ ] Review SLOs, KPIs and AI acceptance rate weekly; triage feedback

### Phase 5 — Scope extension (after the pilot)

- [ ] M2C SIR Reference, Export and Technical SIR/SIRG sheets, ordered by pilot feedback

## Business dependencies and open questions

These sit outside the code but gate the pilot; start chasing them in Phase 0 because answers take weeks.

| Dependency | Needed from | Blocks |
| --- | --- | --- |
| Newer beta package `2.10.9-beta.2` or later | CCRE / config package owners | Correct DE POA and BG IOSS coverage; sanity checks |
| Answers to Q-01 … Q-13 (old expiry dates, "4" in *Waived to Validate*, `TEST` hold-code rules, orphan SIR Reference lines NO/LB/DK/BH, extra Validation list values, duplicate AU·GSTE) | Business and CCRE consultants | Clean `sirdb` load; trustworthy pick-lists |
| Hosting platform choice and namespace | DHL platform / infra team | Phase 3 deployment |
| IdP app registration and role groups | IAM team | SSO |
| Apigee production API key and quota | API platform team | Real AI in TEST/UAT/PROD |
| CRMS TEST/UAT access from the hosting network (not only VPN) | CRMS team, network | Real-environment run |
| SMTP relay and sender address | Messaging team | Approval and DMG emails |
| Data classification, retention periods, InfoSec review slot | InfoSec, compliance | Go-live |
| Pilot country and named users per role | Business sponsor | Phase 4 |

**Open questions for you**

- Do LLM and UAT calls run synchronously inside request handlers today?
- Which container platform does DHL mandate for internal apps of this class?
- Is the expected user count tens or hundreds? It decides replica sizing, not the architecture.

Agent-level design (each agent's inputs, tools, steps, outputs, guardrails and evaluation): see `docs/design/agent-design.md`.
