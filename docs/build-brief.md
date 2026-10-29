# ARIA build brief

The working specification for ARIA, refined from the owner's requests with the
[prompt-master](https://github.com/nidhinjs/prompt-master) skill. Every acceptance check is
binary; the project is done when all of them pass.

## Objective

Build ARIA into a deployment-grade, end-to-end incident-triage product: an agentic backend, a
polished frontend, measured evals and one-command deploys. Alerts and logs flow through
correlation, triage, investigation and retrieval into an evidence-cited report that a human
approves, and approved reports feed back into memory. Every headline number comes from
`make eval`.

## Context

- Owner profile: experienced engineer targeting AI/LLM, ML and backend/cloud roles.
- Stack: Python 3.13 + uv, LangGraph 1.2, langchain-core 1.7, MCP Python SDK 2.3, FastAPI,
  SQLAlchemy 2.1, Pydantic 2.14, Azure SQL / SQLite. `langchain-mcp-adapters` is not used: it
  pins `mcp<2`, and ARIA calls MCP tools directly rather than handing them to an LLM.
- Data: Loghub (~500k events) and the UCI ServiceNow incident log (24,918 incidents, 141,712
  events).
- Flaws in the original pitch that the build fixes:
  - Only measured metrics are published.
  - Severity labels come from dataset ground truth through a documented rubric that is
    independent of the rule features.
  - Loghub and UCI are never linked artificially. UCI supplies priority, SLA and repeat
    statistics; fixes come from a runbook library.
  - Semantic validators catch well-formed wrong answers that Pydantic can't.
  - Calibrated probabilities plus conformal prediction sets replace the arbitrary 85% gate.
  - Model names come from config, verified against provider docs (GPT-4 is retired).
  - Every LLM-written claim cites evidence IDs.
  - Prompt-injection, PII, cost and human-approval controls are built in.

## Target state

1. **Pipeline:** ingest → alert correlation/dedup → parse (Drain templates, windows, features) →
   severity (rules → calibrated model → conformal set → LLM adjudication only inside the set) →
   investigation → retrieval → report → critic → human review → publish → learn.
2. **Agentic features**, each implemented and tested:
   - A supervisor/planner with plan state, replanning on low confidence or a failed
     validation, and wider retrieval and context on retry.
   - Specialist agents as LangGraph subgraphs with Pydantic-checked handoffs: Parser, Severity,
     Investigator (hypothesis loop over log-query tools, with bounded steps), Retrieval (query
     rewriting, hybrid BM25 + dense search, reranking, retrieval grading and re-query),
     Reporter, Critic (groundedness and completeness, repair loop, deterministic fallback) and
     Comms (stakeholder-update and postmortem drafts).
   - Parallel fan-out over components and windows (Send / map-reduce).
   - An MCP tool layer (server + client) with a tool allowlist, per-run tool budgets and a
     tool-call audit log.
   - Human-in-the-loop: approve, edit or reject interrupts, and an approval gate on every
     outbound action (Slack, Teams or webhook posts, ticket drafts).
   - Durable checkpoints with time travel: inspect state history, replay a run, fork it from
     any checkpoint.
   - Memory: approved reports update incident memory; reviewer feedback goes to an
     active-learning queue and triggers recalibration.
   - Guardrails: injection detection, PII and secret redaction, output policy checks, plus NIM
     safety models or Azure Prompt Shields when configured.
   - Per-run budgets for tokens, cost, latency and steps, degrading gracefully to rules-only.
   - Model routing per node, with a fallback chain and circuit breakers.
   - SSE streaming of node events and LLM tokens.
   - "Ask ARIA": chat over a run's evidence, with citations.
   - Event and scheduled triggers: Alertmanager, Grafana and generic webhooks, plus a periodic
     anomaly scan.
3. **LLM providers**, switched by config only: NVIDIA NIM (the hosted API and self-hosted NIM
   containers; chat, embeddings and reranking), Azure OpenAI, any OpenAI-compatible endpoint,
   and a deterministic fake that runs everything offline. Endpoints and model IDs are verified
   against provider docs; anything unverified is flagged in config.
4. **Backend:** FastAPI (runs, SSE, review, time travel, Ask ARIA, incidents, runbooks, tickets,
   eval, feedback, webhooks, a mounted MCP endpoint, health and readiness checks, Prometheus
   metrics), API-key auth and rate limits, a worker process for background runs, SQLAlchemy +
   Alembic on SQLite and Azure SQL with a SQLAlchemy checkpointer, and OpenTelemetry traces with
   GenAI attributes plus token, cost and latency per run.
5. **Evaluation:** `make eval` writes versioned JSON, `docs/evaluation.md` and a CI regression
   gate, covering:
   - log severity: macro-F1, per-class recall, under-triage rate, weighted kappa, ECE,
     risk–coverage and auditable share, with bootstrap CIs, against majority, keyword,
     rules-only, ML-only, LLM-only and hybrid baselines;
   - UCI priority and SLA-breach prediction on a time-based split;
   - parser grouping accuracy against Loghub's ground-truth templates;
   - retrieval Recall@3, MRR and nDCG;
   - report groundedness;
   - 2,000 edge-case and injection inputs;
   - p50/p95 latency and cost per provider.
6. **Frontend (`web/`):**
   - Stack: Next.js App Router, strict TypeScript, Tailwind v4, shadcn/ui, 21st.dev components,
     React Bits, GSAP (ScrollTrigger), Motion.
   - Design system: OKLCH color tokens, dark-first with a light theme, a type scale with a mono
     face for logs, a 4px grid, defined motion durations and easings.
   - Landing page: animated hero, pipeline and agent-graph animation, measured results.
   - App: overview KPIs, incident queue, a run view (live agent timeline; severity with rule
     trace, probabilities and prediction set; evidence explorer; similar incidents; cited
     report with hover-to-evidence; approvals; time travel), Ask ARIA, eval dashboard, memory
     and runbooks, and settings (providers including NIM, budgets, guardrails).
   - Every view has loading, empty and error states.
7. **Video (`video/`):** a 60–90 s Remotion explainer and demo built from real run output,
   rendered to MP4.
8. **Deployment:** multi-stage Docker images (api, worker, web); docker compose with an optional
   NIM profile; Bicep + azd (Container Apps or App Service, Azure SQL, Azure OpenAI, Key Vault,
   App Insights, managed identity); GitHub Actions CI (lint, types, tests, eval gate, web
   checks, image builds, pip-audit, pnpm audit, Bicep build) and a manually triggered OIDC
   deploy.
9. **Docs:** a README (architecture diagram, quickstart, provider setup including NIM, measured
   results, limitations), ADRs, a data card, a model card, a threat model and an ops runbook.

## Constraints

- ruff and mypy `--strict` on `src/`; pytest with Hypothesis; pinned dependencies.
- No secrets in code, logs or git. Config comes from environment variables and Key Vault.
- Tests, the eval smoke run and the demo all run offline with the fake provider.
- Fast-moving facts (model IDs, endpoints, SDK and spec versions, Azure and NIM offers) are
  verified against official docs; anything unverified is flagged.
- Raw datasets stay out of git: download scripts and checksums only, plus small fixtures.
- Design quality bars: WCAG 2.2 AA; Lighthouse ≥95 on every category for the landing page and
  ≥90 performance on app pages; CLS < 0.05; `prefers-reduced-motion` honored; responsive from
  375 to 1920 px; full keyboard navigation; zero console errors.

## Acceptance criteria

- [ ] `make test` passes, with ≥80% line coverage on `src/aria`.
- [ ] `make eval` reproduces every number quoted in the README and docs, and the CI gate fails
      on a regression.
- [ ] `make dev` runs the stack. A sample alert goes through correlation and triage, streams to
      the UI, pauses for approval, publishes a cited report and updates memory.
- [ ] Every agentic feature listed above has at least one test that exercises it.
- [ ] The Azure OpenAI, NVIDIA NIM and OpenAI-compatible adapters pass contract tests against
      mocked HTTP. Switching provider takes a config change only.
- [ ] Every report claim resolves to an existing evidence ID. The injection suite never changes
      severity or tool use, and budgets hold.
- [ ] The MCP server passes a client round-trip test over stdio and streamable HTTP.
- [ ] Web build, lint, typecheck and Playwright pass. Lighthouse and axe meet the bars above.
      Screenshots at 375, 768 and 1440 px in both themes have been reviewed.
- [ ] `docker compose up` comes up healthy, `bicep build` passes, and actionlint passes.
- [ ] The Remotion video renders to MP4.
- [ ] The README states the limitations and labels synthetic data as synthetic.
