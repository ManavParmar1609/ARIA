# 0001. One LangGraph graph of specialist nodes

## Status

Accepted. This departs from the [build brief](../build-brief.md), which asked for each specialist
agent to be a LangGraph subgraph (see Consequences).

## Context

A triage run passes through parsing, severity, retrieval, investigation, reporting, comms and
human review. Three properties of a run shaped how to structure it:

- The specialists share most of their working state. Every step reads and extends one evidence
  registry (ids `E1`, `E2`, ...) and one per-run budget. Severity and retrieval run in parallel
  and must not hand out the same evidence ids.
- Runs are durable and inspectable. The API and the console list a run's checkpoints, show its
  state at any step and fork a new run from any checkpoint.
- A run pauses for human review with `interrupt()`, possibly for days, and resumes in whichever
  process receives the decision. On resume LangGraph re-runs the interrupted node from the top;
  inside a subgraph it re-runs both the subgraph's node and the parent node that called it.

## Decision

The workflow is one `StateGraph` over one state type, in
[`workflow.py`](../../src/aria/graph/workflow.py):

- Specialists are nodes: `plan`, `parse_shard` (one task per shard, sent with `Send`; input over
  4,000 lines splits into up to eight shards), `merge`, `severity` and `recall` (in parallel),
  `investigate`, `assess`, `widen`, `report`, `comms`, `review`, `publish` and `reject`. Agents with loops live in plain classes that a node
  calls, such as the bounded ReAct [`Investigator`](../../src/aria/agents/investigator.py).
- Handoffs are checked at node boundaries. State holds JSON
  ([`state.py`](../../src/aria/graph/state.py)); each node validates what it reads into the
  Pydantic contracts in [`contracts/`](../../src/aria/contracts/) and dumps what it writes.
- Parallel writes go through reducers: evidence merges by id, budget usage sums per-node deltas
  and audit lists append. Retrieval, which runs beside severity, takes its evidence ids from a
  separate block, so the two never collide.
- `assess` routes with `Command`, back to `widen` (a replan) or on to `report`. `review` is the
  only node that interrupts, and nothing in it before `interrupt()` has side effects.
- Every node shares one retry policy (transient database and network errors) and an error
  handler that ends the run as failed with the reason. Nodes that call models or tools have run
  and idle timeouts, and `parse_shard` has a cache policy. Its cache
  ([`cache.py`](../../src/aria/graph/cache.py)) holds at most 16 MB, so large pastes cannot grow
  the API's memory.

## Alternatives considered

- **A subgraph per specialist.** It matches the brief, but every boundary would need its own
  state schema and a mapping in and out of the shared evidence registry and budget. Checkpoints
  would be namespaced per subgraph, which complicates history and forking: with LangGraph's
  default subgraph checkpointer setting, a subgraph's state can be inspected only for the current
  invocation. An interrupt inside a subgraph would also re-run its parent node on resume.
- **A supervisor agent handing off to agent subgraphs.** This puts routing in an LLM. ARIA's
  routing is a fixed pipeline plus one deterministic replan rule, which is cheaper, auditable and
  testable offline.

## Consequences

- History, replay and forking work on one thread with one checkpoint namespace
  ([`runner.py`](../../src/aria/graph/runner.py)), and one stream gives the SSE and AG-UI
  endpoints a step per node.
- The brief's "specialist agents as LangGraph subgraphs" is not met as written. The specialists
  are separable as classes and contracts, not as compiled graphs, so one cannot be deployed,
  versioned or checkpointed on its own.
- `workflow.py` is long (about 1,000 lines). It can be split into modules without changing the
  graph.
- If a specialist ever needs private loop state with its own checkpoints, such as a multi-turn
  investigator, it can become a subgraph then; the contracts at its boundary already exist.
