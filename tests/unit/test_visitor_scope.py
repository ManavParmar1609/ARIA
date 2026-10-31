"""Each visitor's own incidents on a shared public demo (ARIA_VISITOR_SCOPE=true)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from mcp import Client
from sqlalchemy import func, insert, inspect, select

from aria.api.app import create_app
from aria.api.state import AppState
from aria.api.visitors import ANONYMOUS, visitor_tag
from aria.config import GuardrailConfig, reset_caches
from aria.contracts.inputs import TriageRequest
from aria.contracts.report import ReviewDecision
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.db import repository as repo
from aria.db.engine import get_engine, init_db, session_scope
from aria.db.models import FeedbackRow, IncidentRow, RunRow
from aria.evidence import EvidenceStore
from aria.mcp.server import build_server
from aria.parsing.parser import parse_lines
from aria.retrieval.memory import IncidentMemory, run_incident_id
from aria.retrieval.runbooks import load_runbooks
from aria.retrieval.runlog import store_run_lines
from aria.retrieval.seed import incident_from_scenario
from aria.services import Services

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"
ALICE = {"X-Visitor-Id": "alice-0123456789abcdef"}
BOB = {"X-Visitor-Id": "bob-0123456789abcdef0"}


@dataclass
class Demo:
    client: httpx.AsyncClient
    app: FastAPI
    builder: ScenarioBuilder
    example: str  # a run the server started itself: every visitor's example

    @property
    def state(self) -> AppState:
        state: AppState = self.app.state.aria
        return state


async def _seed() -> ScenarioBuilder:
    engine = get_engine()
    init_db(engine)
    builder = ScenarioBuilder(LinePools.from_loghub(FIXTURES))
    runbooks = load_runbooks(Path("runbooks"))
    incidents = [
        incident_from_scenario(
            builder.build(mode, seed=7, nodes=3, duration_min=5, incident_per_min=6), runbooks
        )
        for mode in ("bgl.kernel_panic", "openssh.bruteforce")
    ]
    await IncidentMemory(engine, None).bulk_insert(incidents)
    return builder


def _logs(builder: ScenarioBuilder, seed: int = 8) -> list[str]:
    scenario = builder.build(
        "bgl.kernel_panic", seed=seed, nodes=4, duration_min=6, background_per_min=6
    )
    return scenario.lines


@asynccontextmanager
async def _serve(monkeypatch: pytest.MonkeyPatch, **env: str) -> AsyncIterator[Demo]:
    """The API as the public demo runs it, with one example the server triaged itself."""
    monkeypatch.setenv("ARIA_RATE_LIMIT_PER_MINUTE", "100000")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    reset_caches()
    builder = await _seed()
    app = create_app()
    async with LifespanManager(app) as manager:
        state: AppState = app.state.aria
        request = TriageRequest(system="bgl", title="Example kernel panics", logs=_logs(builder))
        example = await state.runner.start(request, trigger="cli")
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:8000", timeout=60
        ) as client:
            yield Demo(client, app, builder, example.run_id)


@pytest.fixture
async def demo(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Demo]:
    async with _serve(monkeypatch, ARIA_VISITOR_SCOPE="true") as served:
        yield served


async def _wait_for(
    demo: Demo, run_id: str, headers: dict[str, str], *statuses: str
) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while True:
        detail: dict[str, Any] = (
            await demo.client.get(f"/api/v1/runs/{run_id}", headers=headers)
        ).json()
        if detail.get("status") in statuses:
            return detail
        if time.monotonic() > deadline:
            msg = f"run {run_id} stayed {detail.get('status')}"
            raise AssertionError(msg)
        await asyncio.sleep(0.05)


async def _start(demo: Demo, headers: dict[str, str]) -> str:
    body = {"system": "bgl", "title": "Kernel panics", "logs": _logs(demo.builder, seed=9)}
    created = await demo.client.post("/api/v1/runs", json=body, headers=headers)
    assert created.status_code == 202, created.text
    run_id: str = created.json()["run_id"]
    await _wait_for(demo, run_id, headers, "awaiting_review")
    return run_id


async def _listed(demo: Demo, headers: dict[str, str]) -> dict[str, bool]:
    """Run id → whether it is an example, as this caller's incident list shows it."""
    page = (await demo.client.get("/api/v1/runs", headers=headers)).json()
    return {run["id"]: run["example"] for run in page["runs"]}


async def test_each_visitor_sees_their_own_incidents_and_the_examples(demo: Demo) -> None:
    mine = await _start(demo, ALICE)
    assert await _listed(demo, ALICE) == {mine: False, demo.example: True}
    assert await _listed(demo, BOB) == {demo.example: True}
    assert await _listed(demo, {}) == {demo.example: True}  # no session: the examples only

    for path in ("", "/state", "/events", "/history", "/report", "/report.md", "/stream"):
        seen = await demo.client.get(f"/api/v1/runs/{mine}{path}", headers=BOB)
        assert seen.status_code == 404, path  # another visitor's run is as missing as no run
    for path in ("", "/state", "/events", "/history"):
        own = await demo.client.get(f"/api/v1/runs/{mine}{path}", headers=ALICE)
        assert own.status_code == 200, path
    asked = await demo.client.post(
        "/api/v1/ask", json={"question": "What failed?", "run_id": mine}, headers=BOB
    )
    assert asked.status_code == 404
    assert (await demo.client.get(f"/api/v1/runs/{mine}", headers=ALICE)).json()["example"] is False
    example = (await demo.client.get(f"/api/v1/runs/{demo.example}", headers=BOB)).json()
    assert example["example"] is True
    assert "visitor" not in example

    # The database keeps a hash of the session id, never the id itself.
    stored = repo.get_run(demo.state.services.engine, mine)
    assert stored is not None
    assert stored["visitor"] == visitor_tag(ALICE["X-Visitor-Id"])
    assert "alice" not in stored["visitor"]
    settings = (await demo.client.get("/api/v1/settings")).json()
    assert settings["visitor_scope"] is True


async def test_nobody_may_change_an_example_but_anyone_may_copy_it(demo: Demo) -> None:
    example = demo.example
    for method, path, body in (
        ("POST", f"/api/v1/runs/{example}/review", {"decision": "approve"}),
        ("POST", f"/api/v1/runs/{example}/actions/act-1/resend", None),
        ("DELETE", f"/api/v1/runs/{example}", None),
    ):
        refused = await demo.client.request(method, path, json=body, headers=ALICE)
        assert refused.status_code == 403, path
        assert "shared by every visitor" in refused.json()["detail"]
    detail = (await demo.client.get(f"/api/v1/runs/{example}", headers=ALICE)).json()
    assert detail["status"] == "awaiting_review"  # still waiting for the next visitor

    history = (await demo.client.get(f"/api/v1/runs/{example}/history", headers=ALICE)).json()
    waiting = next(c for c in history if c["next"] == ["review"])
    forked = await demo.client.post(
        f"/api/v1/runs/{example}/fork",
        json={"checkpoint_id": waiting["checkpoint_id"]},
        headers=ALICE,
    )
    assert forked.status_code == 202, forked.text
    copy = forked.json()["run_id"]
    mine = await _wait_for(demo, copy, ALICE, "awaiting_review")
    assert (mine["example"], mine["parent_run_id"]) == (False, example)
    assert copy not in await _listed(demo, BOB)
    approved = await demo.client.post(
        f"/api/v1/runs/{copy}/review", json={"decision": "approve"}, headers=ALICE
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "published"
    assert (await demo.client.delete(f"/api/v1/runs/{copy}", headers=BOB)).status_code == 404
    assert (await demo.client.delete(f"/api/v1/runs/{copy}", headers=ALICE)).status_code == 204


async def test_a_visitors_run_never_teaches_the_shared_demo(demo: Demo) -> None:
    """A visitor's approved run stays theirs: it joins neither the incident library other
    visitors search nor the reviews that recalibrate the model. The server's own runs do."""
    engine = demo.state.services.engine

    def remembered(run_id: str) -> tuple[bool, bool]:
        with session_scope(engine) as session:
            incident = session.get(IncidentRow, run_incident_id(run_id)) is not None
            reviewed = session.scalar(
                select(func.count()).select_from(FeedbackRow).where(FeedbackRow.run_id == run_id)
            )
        return incident, bool(reviewed)

    mine = await _start(demo, ALICE)
    approved = await demo.client.post(
        f"/api/v1/runs/{mine}/review",
        json={"decision": "approve", "reviewer": "alice"},
        headers=ALICE,
    )
    assert approved.json()["status"] == "published"
    assert remembered(mine) == (False, False)

    decision = ReviewDecision(decision="approve", reviewer="owner")
    outcome = await demo.state.runner.resume(demo.example, decision)
    assert str(outcome.status) == "published"
    assert remembered(demo.example) == (True, True)


async def test_a_session_id_must_look_like_one(demo: Demo) -> None:
    refused = await demo.client.get("/api/v1/runs", headers={"X-Visitor-Id": "short"})
    assert refused.status_code == 422
    assert "X-Visitor-Id" in refused.json()["detail"]
    odd = await demo.client.get("/api/v1/runs", headers={"X-Visitor-Id": "a" * 20 + "/../x"})
    assert odd.status_code == 422


async def test_without_scoping_or_with_a_key_every_run_is_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with _serve(monkeypatch) as plain:  # self-hosted: no scoping
        mine = await _start(plain, ALICE)
        assert await _listed(plain, BOB) == {mine: False, plain.example: False}
        stored = repo.get_run(plain.state.services.engine, mine)
        assert stored is not None
        assert stored["visitor"] is None

    async with _serve(monkeypatch, ARIA_VISITOR_SCOPE="true", ARIA_API_KEYS="ana:k-ana") as keyed:
        owner = {"Authorization": "Bearer k-ana"}
        theirs = await _start(keyed, {**owner, **ALICE})  # a key wins over a session id
        listed = await _listed(keyed, owner)  # this database also holds the first server's runs
        assert {theirs, keyed.example} <= set(listed)
        assert not any(listed.values())
        stored = repo.get_run(keyed.state.services.engine, theirs)
        assert stored is not None
        assert stored["visitor"] is None


async def test_alerts_from_two_visitors_never_join_one_incident(demo: Demo) -> None:
    payload = [{"name": "DiskFull", "fingerprint": "a", "labels": {"system": "bgl"}}]
    alice = (await demo.client.post("/api/v1/alerts", json=payload, headers=ALICE)).json()
    bob = (await demo.client.post("/api/v1/alerts", json=payload, headers=BOB)).json()
    assert alice["run_id"] != bob["run_id"]
    assert alice["alert_group_id"] != bob["alert_group_id"]
    again = (await demo.client.post("/api/v1/alerts", json=payload, headers=ALICE)).json()
    assert (again["run_id"], again["grouped"]) == (alice["run_id"], True)
    assert (
        await demo.client.get(f"/api/v1/runs/{bob['run_id']}", headers=ALICE)
    ).status_code == 404
    anonymous = (await demo.client.post("/api/v1/alerts", json=payload)).json()
    stored = repo.get_run(demo.state.services.engine, anonymous["run_id"])
    assert stored is not None
    assert stored["visitor"] == ANONYMOUS  # never an example everyone would see


def _sse(text: str) -> list[dict[str, Any]]:
    import json

    out: list[dict[str, Any]] = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                out.append(json.loads(line[5:].strip()))
    return out


async def test_agui_threads_are_a_visitors_own(demo: Demo) -> None:
    mine = await _start(demo, ALICE)
    taken = {"threadId": mine, "runId": "ui-1", "messages": []}
    events = _sse((await demo.client.post("/agui", json=taken, headers=BOB)).text)
    assert (events[0]["type"], events[-1]["type"]) == ("RUN_STARTED", "RUN_ERROR")
    assert events[-1]["code"] == "thread_taken"

    review = {
        "threadId": demo.example,
        "runId": "ui-2",
        "messages": [],
        "resume": [{"interruptId": "x", "status": "resolved", "payload": {"decision": "approve"}}],
    }
    events = _sse((await demo.client.post("/agui", json=review, headers=ALICE)).text)
    assert (events[-1]["type"], events[-1]["code"]) == ("RUN_ERROR", "shared_example")
    detail = (await demo.client.get(f"/api/v1/runs/{demo.example}", headers=ALICE)).json()
    assert detail["status"] == "awaiting_review"

    fresh = {
        "threadId": "alice-thread-1",
        "runId": "ui-3",
        "messages": [{"id": "u1", "role": "user", "content": "\n".join(_logs(demo.builder))}],
        "forwardedProps": {"system": "bgl"},
    }
    events = _sse((await demo.client.post("/agui", json=fresh, headers=ALICE)).text)
    assert events[-1]["type"] == "RUN_FINISHED"
    started = [r for r, example in (await _listed(demo, ALICE)).items() if not example]
    assert len(started) == 2
    assert len(await _listed(demo, BOB)) == 1


async def test_a2a_tasks_belong_to_the_visitor_who_sent_them(demo: Demo) -> None:
    message = {
        "messageId": "m1",
        "role": "ROLE_USER",
        "parts": [{"text": "\n".join(_logs(demo.builder))}],
        "metadata": {"system": "bgl"},
    }
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": message}}
    headers = {**ALICE, "A2A-Version": "1.0"}
    task = (await demo.client.post("/a2a", json=rpc, headers=headers)).json()["result"]["task"]
    run_id = f"a2a-{task['id']}"
    assert run_id in await _listed(demo, ALICE)
    assert (await demo.client.get(f"/api/v1/runs/{run_id}", headers=BOB)).status_code == 404

    reply = {
        "messageId": "m2",
        "role": "ROLE_USER",
        "taskId": task["id"],
        "contextId": task["contextId"],
        "parts": [{"data": {"decision": "approve"}}],
    }
    rpc = {"jsonrpc": "2.0", "id": 2, "method": "SendMessage", "params": {"message": reply}}
    other = {**BOB, "A2A-Version": "1.0"}
    answered = (await demo.client.post("/a2a", json=rpc, headers=other)).json()
    assert "error" in answered  # as missing as a task that never existed
    stored = repo.get_run(demo.state.services.engine, run_id)
    assert stored is not None
    assert stored["status"] == "awaiting_review"  # Bob's answer changed nothing


async def test_the_open_mcp_endpoint_reads_only_the_examples_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ARIA_VISITOR_SCOPE", "true")
    reset_caches()
    engine = get_engine()
    init_db(engine)
    builder = ScenarioBuilder(LinePools.from_loghub(FIXTURES))
    out = parse_lines(
        _logs(builder), system="bgl", guard=GuardrailConfig(), evidence=EvidenceStore()
    )
    for run_id, visitor in (("run-example", None), ("run-alice", visitor_tag("alice-session-1"))):
        repo.create_run(engine, run_id, request={}, system="bgl", visitor=visitor)
        store_run_lines(engine, run_id, "bgl", out.lines)
    svc = await Services.create()
    try:
        async with Client(build_server(svc, mounted=True)) as client:
            for run_id, expected in (("run-example", True), ("run-alice", False)):
                found = await client.call_tool(
                    "search_logs", {"query": "kernel", "run_id": run_id, "limit": 3}
                )
                assert bool(found.structured_content["lines"]) is expected, run_id
                nodes = await client.call_tool("node_breakdown", {"run_id": run_id})
                assert bool(nodes.structured_content["nodes"]) is expected, run_id
            by_system = await client.call_tool(
                "search_logs", {"query": "kernel", "system": "bgl", "limit": 50}
            )
            assert by_system.structured_content["lines"] == []  # runs' own lines stay out
        async with Client(build_server(svc)) as investigator:  # the in-process tool server
            found = await investigator.call_tool(
                "search_logs", {"query": "kernel", "run_id": "run-alice", "limit": 3}
            )
            assert found.structured_content["lines"]
    finally:
        await svc.aclose()


def test_the_migration_gives_earlier_runs_no_visitor(tmp_path: Path) -> None:
    from sqlalchemy import create_engine

    from aria.db import migrate

    url = f"sqlite:///{tmp_path / 'old.db'}"
    migrate.upgrade("b3c1f0a9d2e4", url=url)
    engine = create_engine(url)
    now = datetime.now(UTC)
    with engine.begin() as conn:
        conn.execute(
            insert(RunRow.__table__).values(
                id="run-before",
                created_at=now,
                updated_at=now,
                status="published",
                trigger="cli",
                system="bgl",
                request={},
                providers=[],
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
            )
        )
    migrate.upgrade("head", url=url)
    columns = {c["name"] for c in inspect(engine).get_columns("runs")}
    assert "visitor" in columns
    with engine.connect() as conn:
        assert (
            conn.execute(select(RunRow.visitor).where(RunRow.id == "run-before")).scalar() is None
        )
    engine.dispose()
