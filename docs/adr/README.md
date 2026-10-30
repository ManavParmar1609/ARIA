# Architecture decision records

The decisions that shaped ARIA, in the format Michael Nygard described in
[Documenting architecture decisions](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).
Each record says what forced the choice, what was decided, what else was considered and what
follows from it. Records that depart from the [build brief](../build-brief.md) say so in their
status. Measured results live in [the evaluation](../evaluation.md), not here.

| ADR | Title | Status | Decision |
|---|---|---|---|
| [0001](0001-one-langgraph-graph-of-specialist-nodes.md) | One LangGraph graph of specialist nodes | Accepted (departs from the brief) | One `StateGraph` with a node per specialist and shared, reducer-merged state, instead of a subgraph per agent. |
| [0002](0002-severity-cascade-with-conformal-sets.md) | Severity: rules, a calibrated model and a conformal set, then the LLM | Accepted | Rules, a temperature-calibrated model and a split-conformal set decide severity; an LLM may choose only inside the set. |
| [0003](0003-severity-ground-truth-from-tags-and-a-written-policy.md) | Severity ground truth from dataset tags and a written policy | Accepted | BGL windows take labels from sysadmin alert tags, other systems from a documented scenario policy, on semi-synthetic windows with disjoint seeds. |
| [0004](0004-keep-loghub-and-uci-separate.md) | Keep Loghub and the UCI incident log separate | Accepted | The datasets are never joined: UCI serves ticket priority and SLA history, and fixes come from the runbook library. |
| [0005](0005-route-model-calls-through-provider-chains.md) | Route model calls by role through config-defined provider chains | Accepted | Per-role fallback chains over Gemini, NIM, Azure OpenAI, OpenAI-compatible and a fake provider, with circuit breakers and per-run budgets. |
| [0006](0006-call-mcp-tools-through-an-allowlisted-tool-belt.md) | Call MCP tools directly through an allowlisted tool belt | Accepted | A read-only MCP server and a client-side tool belt with an allowlist, run pinning, budgets and an audit log; no `langchain-mcp-adapters`. |
| [0007](0007-every-report-claim-cites-evidence.md) | Every report claim cites evidence, with a deterministic fallback | Accepted | Deterministic grounding checks gate every report, a critic removes weak claims, and a template draft is the fallback. |
| [0008](0008-keep-runs-checkpoints-and-memory-in-one-sql-database.md) | Keep runs, checkpoints and memory in ARIA's own SQL database | Accepted | One Alembic schema on SQLite or Azure SQL, with ARIA's own LangGraph checkpointer and Store for time travel and forks. |
| [0009](0009-speak-a2a-ag-ui-and-mcp.md) | Speak A2A, AG-UI and MCP beside the REST API | Accepted | One API process serves REST/SSE, A2A, AG-UI and MCP, and maps the review pause onto each protocol. |
| [0010](0010-backend-for-frontend-keeps-the-api-key-from-page-scripts.md) | A backend-for-frontend keeps the API key away from page scripts | Accepted | The Next.js server holds the key in an HttpOnly cookie and forwards same-origin requests to the API. |
| [0011](0011-recalibrate-only-the-conformal-threshold-from-reviews.md) | Recalibrate only the conformal threshold from human reviews | Accepted | Reviews recalibrate the conformal threshold only, with versioned, atomic model swaps that running engines reload. |
| [0012](0012-content-safety-check-is-optional-and-fails-closed.md) | The content-safety check is optional and fails closed | Accepted (off by default) | A safety model can screen LLM-written text; any doubt falls back to deterministic text. |
| [0013](0013-run-background-jobs-where-runs-execute.md) | Run the scan and recalibration jobs where runs execute | Accepted | Periodic jobs start in the API in `inprocess` mode and in `aria worker` in `external` mode. |

## Adding a record

Copy the headings of an existing record (Status, Context, Decision, Alternatives considered,
Consequences), give it the next number and add a row above. When a decision changes, write a new
record that supersedes the old one, and set the old record's status to point at it.
