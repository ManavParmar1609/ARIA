# 0009. Speak A2A, AG-UI and MCP beside the REST API

## Status

Accepted.

## Context

Besides its own console, ARIA has three kinds of client: agents that want to delegate a triage,
user interfaces built on agent frameworks, and assistants that want ARIA's evidence tools. Each
has an open protocol. Whatever the protocol, the human-review pause has to survive it: the client
must see that a run is waiting and be able to answer.

## Decision

One API process ([`app.py`](../../src/aria/api/app.py)) serves every protocol, behind the same
API-key middleware and rate limiter:

- **REST and SSE** under `/api/v1` stay the primary interface. The console's run view follows
  `/api/v1/runs/{id}/stream`, which replays stored events after `Last-Event-ID` and then follows
  the run live, polling the database when another process executes it
  ([`sse.py`](../../src/aria/api/sse.py)).
- **A2A** ([`a2a.py`](../../src/aria/api/a2a.py), [a2a-sdk](https://pypi.org/project/a2a-sdk/)
  1.3): an Agent Card at `/.well-known/agent-card.json` (public) and JSON-RPC at `/a2a`. Each task
  is one ARIA run, `a2a-<task id>`:
  - the first message carries log lines as text, or a `TriageRequest` as a data part;
  - when the report waits for review, the task moves to `input-required`, with the report
    attached as an artifact;
  - a follow-up message on the same task carries the decision, and cancelling the task rejects
    the report.
- **AG-UI** ([`agui.py`](../../src/aria/api/agui.py),
  [ag-ui-protocol](https://pypi.org/project/ag-ui-protocol/) 1.0): `POST /agui` takes a
  `RunAgentInput`, and the thread is the run.
  - The response is an event stream: `RUN_STARTED`, a step per graph node, `TOOL_CALL_*` events
    for the investigator's MCP calls, the report as an assistant text message, `CUSTOM` events for
    ARIA's own signals, a `STATE_SNAPSHOT`, and `RUN_FINISHED` with an `interrupt` outcome while
    the report waits for review.
  - A `resume` entry answers the interrupt.
  - The console's chat triage uses this endpoint through `@ag-ui/client`.
- **MCP** at `/mcp` and over stdio
  ([0006](0006-call-mcp-tools-through-an-allowlisted-tool-belt.md)).

The review pause maps onto each protocol's own: the LangGraph interrupt becomes A2A's
`input-required` and AG-UI's interrupt outcome, and every path resumes the same run through
`TriageRunner.resume`.

## Alternatives considered

- **REST only.** Every integrator would have to learn ARIA's run and review model.
- **AG-UI for the whole console.** The run view needs replay from any stored event, and runs that
  another process executes. ARIA's own stream already stores and numbers every event, so the run
  view keeps it and AG-UI serves chat-style clients.

## Consequences

- Another agent can hand ARIA an incident, and a framework UI can drive a run, without
  ARIA-specific client code, and both meet the same review gate.
- The A2A server keeps tasks in an in-memory task store and forgets them on restart. The paused
  run survives (its checkpoints are in the database) and can still be reviewed through the REST
  API or the console.
- Three protocols are three surfaces to keep current. Their SDK versions are pinned in
  [`pyproject.toml`](../../pyproject.toml) and `uv.lock`.
- The brief described AG-UI as the stream the frontend consumes. In practice the run view uses
  ARIA's SSE stream, and AG-UI serves the chat triage.
