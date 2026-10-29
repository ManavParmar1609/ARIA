"""The agents' side of MCP: an allowlisted, budgeted, audited tool belt.

* Only allowlisted tools are visible or callable; anything else fails before a request is sent.
* Every call is checked against the run's tool-call budget first.
* Arguments are filtered to the tool's declared parameters, so stray fields from a model never
  reach the server.
* Every call produces an audit record (``ToolCallRecord``), an OpenTelemetry ``execute_tool``
  span, and, when it succeeds, citable evidence with a short summary of the result.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.client._transport import TransportStreams
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import MCPServer
from mcp.shared._httpx_utils import create_mcp_http_client

from aria.contracts.base import EvidenceKind
from aria.contracts.retrieval import ToolCallRecord
from aria.evidence import EvidenceStore
from aria.llm.budget import BudgetGuard
from aria.observability.tracing import mark_error, tool_span

Target = MCPServer | StdioServerParameters | str | AbstractAsyncContextManager[TransportStreams]


@asynccontextmanager
async def _bearer_http(url: str, token: str) -> AsyncIterator[TransportStreams]:
    client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    async with client, streamable_http_client(url, http_client=client) as streams:
        yield streams


def remote_target(url: str, token: str | None = None) -> Target:
    """A streamable-HTTP MCP endpoint, sending a bearer token when one is given."""
    return _bearer_http(url, token) if token else url


class ToolNotAllowedError(PermissionError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]

    def brief(self) -> dict[str, Any]:
        props = self.parameters.get("properties", {})
        return {"name": self.name, "description": self.description, "arguments": sorted(props)}


@dataclass
class ToolOutcome:
    record: ToolCallRecord
    data: dict[str, Any] | None
    evidence_id: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def summarize(tool: str, args: dict[str, Any], data: dict[str, Any]) -> str:
    """One line a reviewer (or the next agent) can read without opening the payload."""
    if "incidents" in data:
        items = data["incidents"]
        shown = "; ".join(
            f"{i['incident_id']} {i['failure_mode']} ({i['severity']}, {i['occurrences']}x)"
            for i in items[:3]
        )
        return f"{len(items)} similar incidents: {shown}" if items else "no similar incidents"
    if "lines" in data:
        lines = data["lines"]
        more = " (more not shown)" if data.get("truncated") else ""
        return f"{len(lines)} log lines{more}" + (
            f"; first: {lines[0]['message'][:120]}" if lines else ""
        )
    if "buckets" in data:
        buckets = data["buckets"]
        peak = max(buckets, key=lambda b: (b["errors"], b.get("warnings", 0)), default=None)
        if not peak:
            return f"no lines for component {data.get('component')}"
        errors = sum(b["errors"] for b in buckets)
        warnings = sum(b.get("warnings", 0) for b in buckets)
        return (
            f"{data.get('component')}: {sum(b['total'] for b in buckets)} lines over "
            f"{len(buckets)} min, {errors} errors and {warnings} warnings; peak at minute "
            f"{peak['minute']} ({peak['errors']} errors, {peak.get('warnings', 0)} warnings)"
        )
    if "nodes" in data:
        nodes = data["nodes"]
        top = ", ".join(
            f"{n['node']} ({n['errors']} errors, {n.get('warnings', 0)} warnings)"
            for n in nodes[:3]
        )
        erring = sum(1 for n in nodes if n["errors"] or n.get("warnings", 0))
        return f"{erring} nodes with errors or warnings; top: {top}" if nodes else "no nodes"
    if "runbooks" in data:
        return "runbooks: " + ", ".join(r["slug"] for r in data["runbooks"][:3])
    if "mitigate" in data:
        return f"runbook {data.get('slug')}: {len(data['mitigate'])} mitigation steps (risk {data.get('risk')})"
    if "found" in data:
        stats = data.get("stats") or {}
        return (
            f"{stats.get('n_similar', 0)} similar tickets" if data["found"] else "no ticket history"
        )
    return f"{tool}({', '.join(f'{k}={v!r}' for k, v in args.items())}) returned {len(json.dumps(data))} bytes"


class ToolBelt:
    def __init__(
        self,
        target: Target,
        *,
        allowed: Iterable[str],
        agent: str,
        run_id: str,
        evidence: EvidenceStore | None = None,
        budget: BudgetGuard | None = None,
        on_call: Callable[[ToolCallRecord], None] | None = None,
        timeout_s: float = 30.0,
        pin_run: bool = True,
    ) -> None:
        self.target = target
        self.allowed = frozenset(allowed)
        self.agent = agent
        self.run_id = run_id
        self.evidence = evidence
        self.budget = budget
        self.on_call = on_call
        self.timeout_s = timeout_s
        self.pin_run = pin_run
        self.records: list[ToolCallRecord] = []
        self._client: Client | None = None
        self._specs: dict[str, ToolSpec] = {}

    async def __aenter__(self) -> ToolBelt:
        self._client = Client(self.target, read_timeout_seconds=self.timeout_s)
        await self._client.__aenter__()
        listed = await self._client.list_tools()
        self._specs = {
            t.name: ToolSpec(t.name, (t.description or "").strip(), dict(t.input_schema or {}))
            for t in listed.tools
            if t.name in self.allowed
        }
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._client is not None:
            await self._client.__aexit__(exc_type, exc, tb)
            self._client = None

    def specs(self) -> list[ToolSpec]:
        return [self._specs[name] for name in sorted(self._specs)]

    def _record(
        self,
        tool: str,
        args: dict[str, Any],
        *,
        ok: bool,
        summary: str,
        evidence_ids: list[str],
        started: float,
    ) -> ToolCallRecord:
        record = ToolCallRecord(
            call_id=f"tc-{uuid.uuid4().hex[:12]}",
            agent=self.agent,
            tool=tool,
            arguments=args,
            ok=ok,
            summary=summary[:500],
            evidence_ids=evidence_ids,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        self.records.append(record)
        if self.on_call is not None:
            self.on_call(record)
        return record

    def prepared(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """The arguments a call would send: only those the tool accepts, pinned to this run."""
        spec = self._specs.get(tool)
        if spec is None:
            return {k: v for k, v in arguments.items() if v is not None}
        accepted = set(spec.parameters.get("properties", {}))
        args = {k: v for k, v in arguments.items() if k in accepted and v is not None}
        if self.pin_run and "run_id" in accepted:
            args["run_id"] = self.run_id  # ARIA chooses the run, never the model
        return args

    async def call(self, tool: str, arguments: dict[str, Any] | None = None) -> ToolOutcome:
        started = time.perf_counter()
        raw = {k: v for k, v in (arguments or {}).items() if v is not None}
        if tool not in self.allowed or tool not in self._specs:
            self._record(
                tool,
                raw,
                ok=False,
                summary="refused: tool is not on the allowlist",
                evidence_ids=[],
                started=started,
            )
            msg = f"{self.agent} may not call {tool!r}"
            raise ToolNotAllowedError(msg)
        if self._client is None:
            msg = "use 'async with ToolBelt(...)' before calling tools"
            raise RuntimeError(msg)
        if self.budget is not None:
            self.budget.check_tool()
        args = self.prepared(tool, raw)
        with tool_span(tool, agent=self.agent, call_id=self.run_id) as span:
            try:
                result = await self._client.call_tool(tool, args)
            except Exception as exc:  # transport failure: audit it, then let the agent decide
                mark_error(span, exc)
                if self.budget is not None:
                    self.budget.record_tool()
                record = self._record(
                    tool, args, ok=False, summary=f"error: {exc}", evidence_ids=[], started=started
                )
                return ToolOutcome(record, None, None, error=str(exc)[:300])
        if self.budget is not None:
            self.budget.record_tool()
        if result.is_error:
            message = " ".join(getattr(c, "text", "") for c in result.content)[:300] or "tool error"
            record = self._record(
                tool, args, ok=False, summary=message, evidence_ids=[], started=started
            )
            return ToolOutcome(record, None, None, error=message)
        data: dict[str, Any] = dict(result.structured_content or {})
        summary = summarize(tool, args, data)
        evidence_id = None
        if self.evidence is not None:
            evidence_id = self.evidence.add(
                EvidenceKind.TOOL,
                f"{tool}: {summary}"[:200],
                source=f"mcp.{tool}",
                detail=json.dumps(data, default=str)[:3_500],
                data={"tool": tool, "arguments": args, "agent": self.agent},
            )
        record = self._record(
            tool,
            args,
            ok=True,
            summary=summary,
            evidence_ids=[evidence_id] if evidence_id else [],
            started=started,
        )
        return ToolOutcome(record, data, evidence_id)
