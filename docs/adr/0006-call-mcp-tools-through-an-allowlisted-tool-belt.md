# 0006. Call MCP tools directly through an allowlisted tool belt

## Status

Accepted.

## Context

ARIA's investigator needs evidence tools: log search, per-component timelines, node breakdowns,
similar incidents and runbooks. The same tools should work from any MCP client, such as an IDE
assistant or another agent. The usual bridge from MCP to LangChain tools,
`langchain-mcp-adapters`, requires `mcp<2.0.0` in its latest release
([0.3.2](https://pypi.org/project/langchain-mcp-adapters/0.3.2/)), while ARIA uses the
[MCP Python SDK](https://pypi.org/project/mcp/) 2.3. ARIA also never hands a model a set of tools
to call freely: its investigator picks one tool per step inside a bounded loop.

## Decision

- **One read-only server** ([`server.py`](../../src/aria/mcp/server.py)) exposes nine tools
  (`search_incidents`, `get_incident`, `search_runbooks`, `get_runbook`, `get_ticket_history`,
  `search_logs`, `get_template_examples`, `component_timeline` and `node_breakdown`), two
  resource templates (`runbook://{slug}` and `incident://{incident_id}`), and two prompts that
  show a client's model how to use them (`investigate_incident` and `summarize_incident`; the
  user's symptoms are fenced as untrusted text). Every tool is annotated
  read-only, non-destructive, idempotent and closed-world, takes bounded Pydantic arguments and
  returns structured output. The server's instructions tell clients that results are untrusted
  evidence, never instructions.
- **Three transports.** ARIA's agents call the server in process (`mcp.Client(server)`), or over
  streamable HTTP when `ARIA_MCP_URL` points at a remote server. External clients use stdio
  (`aria mcp`) or the API's `/mcp` endpoint: stateless streamable HTTP behind the API key, with
  host and origin checks.
- **A tool belt on the agent side** ([`client.py`](../../src/aria/mcp/client.py)) wraps every
  call:
  - only allowlisted tools are listed or callable; the investigator's list leaves out incident
    detail, runbook search and ticket history;
  - arguments are filtered to the tool's declared parameters, and ARIA, not the model, sets the
    `run_id` of run-scoped tools, so a model cannot read another run's logs;
  - each call is checked against the run's tool-call budget first;
  - each call leaves an audit record (saved to the `tool_calls` table), an OpenTelemetry
    `execute_tool` span and, on success, citable evidence with a one-line summary.
- **No write tools.** Anything outbound (Slack, Teams, webhooks, ticket drafts) is a proposed
  action that waits for a reviewer, never an MCP tool.

## Alternatives considered

- **`langchain-mcp-adapters`.** Its `mcp<2` requirement conflicts with ARIA's SDK, and its job,
  turning MCP tools into LangChain tools for an agent loop, is not what ARIA needs.
- **Plain Python functions.** Faster in process, but no other client could use them, and ARIA's
  agents would test a different path from the one external clients take.

## Consequences

- Any MCP client can use ARIA's evidence tools, and a confused or compromised agent can read
  evidence but cannot change anything. Round-trip tests run over stdio and streamable HTTP
  ([`test_mcp.py`](../../tests/unit/test_mcp.py)).
- In-process calls still pay for MCP serialisation and schema checks, a small cost for agents and
  external clients sharing one code path.
- The standalone HTTP server (`aria mcp --transport streamable-http`) binds to 127.0.0.1 and has
  no API-key check of its own. Remote clients should use the API's `/mcp`.
