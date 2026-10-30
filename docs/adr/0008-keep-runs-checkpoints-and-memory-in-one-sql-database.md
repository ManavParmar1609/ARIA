# 0008. Keep runs, checkpoints and memory in ARIA's own SQL database

## Status

Accepted.

## Context

A run can pause for review for days and must survive restarts. Reviewers inspect its history and
fork it from any step. Several processes share runs: the API and, in `external` mode, one or more
workers. Locally ARIA should need nothing but a file. On Azure it uses Azure SQL with managed
identity and no stored password. The checkpoint savers LangGraph publishes each target one
database, such as SQLite or Postgres, so using one would have meant a second database on Azure.

## Decision

- **One schema under Alembic.** SQLAlchemy 2 models ([`models.py`](../../src/aria/db/models.py))
  and Alembic migrations ([`migrations/`](../../src/aria/db/migrations/)) cover runs and their
  events, reports, actions, tool calls, feedback, alerts, incident memory, runbooks, ITSM history
  and the LangGraph tables. `aria db upgrade` migrates, and the API can migrate on start
  (`ARIA_MIGRATE_ON_START`).
- **Two engines** ([`engine.py`](../../src/aria/db/engine.py)):
  - SQLite in WAL mode, so the API, the worker and SSE readers can share one file;
  - Azure SQL through pyodbc, where `ARIA_DATABASE_AUTH=entra` gives every new connection a
    Microsoft Entra ID token from `DefaultAzureCredential` (managed identity inside Azure).
- **A LangGraph checkpointer on that database** ([`checkpoint.py`](../../src/aria/graph/checkpoint.py)).
  It follows the layout of LangGraph's reference savers: a checkpoint row without its channel
  values, and each channel value stored once per version in `lg_blobs`, so thousands of input
  lines are written once rather than into every checkpoint. It adds `copy_thread` (the basis of
  forking), `delete_thread` and `prune`.
- **A LangGraph Store on that database** ([`store.py`](../../src/aria/graph/store.py)) for memory
  across runs: reviewer corrections by system and failure mode, and the templates seen in
  published runs. Search is lexical, with exact-match filters.
- **Time travel in the runner** ([`runner.py`](../../src/aria/graph/runner.py)). History lists a
  run's checkpoints. A fork copies the thread, gives the new run its own run, report and action
  ids (so it cannot publish over the original), copies the run's log lines, restarts the budget
  clock and continues from the chosen checkpoint.
- **State is JSON-shaped** ([`state.py`](../../src/aria/graph/state.py)), so checkpoints load
  without unpickling anything and stay portable across processes and versions.

## Alternatives considered

- **Postgres with LangGraph's Postgres saver.** A good fit for LangGraph, but on Azure it adds a
  database next to Azure SQL or replaces it.
- **In-memory checkpoints.** Lost on restart, and not shared between the API and the workers.
- **A separate checkpoint store.** Deleting a run would span two systems. With one database,
  `TriageRunner.delete` removes a run's checkpoints, lines, events, report, actions, audit records
  and memory in one place.

## Consequences

- The saver is ARIA's to maintain against LangGraph's checkpoint interface, so
  `langgraph-checkpoint` is pinned below its next major version in
  [`pyproject.toml`](../../pyproject.toml).
- SQLite suits one host. Several hosts need Azure SQL.
- The tests run on SQLite. The Entra token hook is unit-tested with a stand-in driver; no live
  Azure SQL runs in CI.
