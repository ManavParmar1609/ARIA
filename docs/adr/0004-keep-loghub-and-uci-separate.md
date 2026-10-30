# 0004. Keep Loghub and the UCI incident log separate

## Status

Accepted.

## Context

The pitch joined two public datasets: Loghub log events and the UCI "Incident management process
enriched event log", a ServiceNow audit trail of 24,918 incidents. They share no keys, systems or
time range, so any join between them would be invented. The UCI log also holds anonymised codes
(`Category 55`) and no free text ([`uci.py`](../../src/aria/data/uci.py)), so it cannot supply
fix descriptions.

## Decision

The datasets are never linked. Each answers its own question:

- **Loghub** drives everything log-based: parsing, severity, investigation and incident memory.
- **UCI** feeds ticket triage, used only when a run's request carries a `ticket`:
  - two calibrated models predict a ticket's eventual priority (with a conformal set) and its
    risk of breaching its SLA from the fields known when it was opened, trained on the oldest 70%
    by open time ([`ticket.py`](../../src/aria/severity/ticket.py));
  - an impact-by-urgency matrix learned from the data is the auditable rule;
  - outcome statistics of similar tickets come from field equality with a back-off, using only
    tickets opened earlier ([`tickets.py`](../../src/aria/retrieval/tickets.py)), and are also
    the MCP tool `get_ticket_history`.
- **Fixes come from the runbook library** in [`runbooks/`](../../runbooks/): Markdown with front
  matter and risk-tagged steps ([`runbooks.py`](../../src/aria/retrieval/runbooks.py)). A report
  action must name a real runbook, at no lower risk than the runbook's step.
- When a request has both logs and a ticket, the ticket model can only raise a flag: if it rates
  the ticket more severe than the log-based severity, the run is marked for review. It never
  overrides the log decision.

## Alternatives considered

- **Join on time or category.** Any mapping would be fabricated, and retrieval results built on it
  would mean nothing.
- **Generate fix text for UCI tickets with an LLM.** That is made-up data presented as history.

## Consequences

- No result mixes the datasets, and every source is cited for what it actually contains.
- Ticket triage depends on the UCI download. Without it, `POST /api/v1/tickets/assess` returns
  503 ([`learning.py`](../../src/aria/api/routers/learning.py)) and runs skip the ticket model.

**Update, 2026-10-30.** The UCI log now comes from checksum-pinned public copies when UCI's own
site cannot be reached. The ticket models are trained on it and ship in
[`models/severity_ticket.json`](../../models/severity_ticket.json), so `/api/v1/tickets/assess`
answers, and their results are in [evaluation.md](../evaluation.md#real-tickets-a-servicenow-service-desk).
The decision stands: the datasets are still never joined.
