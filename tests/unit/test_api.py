"""The HTTP API: auth, limits, the run lifecycle, SSE, alerts, Ask ARIA, MCP, A2A and AG-UI."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from mcp import Client

from aria.api.app import create_app
from aria.api.state import AppState
from aria.api.worker import heartbeat_age, poll_forever
from aria.config import Environment, get_settings, reset_caches
from aria.contracts.inputs import TriageRequest
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.db import repository as repo
from aria.db.engine import dispose_engines, get_engine, init_db
from aria.graph.runner import TriageRunner
from aria.mcp.client import remote_target
from aria.mcp.server import TOOL_NAMES
from aria.retrieval.memory import IncidentMemory
from aria.retrieval.runbooks import load_runbooks
from aria.retrieval.seed import incident_from_scenario
from aria.services import Services

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"
ANA = {"Authorization": "Bearer k-ana"}
RAJ = {"X-API-Key": "k-raj"}


@dataclass
class Api:
    client: httpx.AsyncClient
    app: FastAPI
    builder: ScenarioBuilder

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
        for mode in ("bgl.kernel_panic", "openssh.bruteforce", "hdfs.block_serve_exceptions")
    ]
    await IncidentMemory(engine, None).bulk_insert(incidents)
    return builder


@pytest.fixture
async def api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Api]:
    monkeypatch.setenv("ARIA_API_KEYS", "ana:k-ana,raj:k-raj")
    reset_caches()
    builder = await _seed()
    app = create_app()
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:8000", headers=ANA, timeout=60
        ) as client:
            yield Api(client, app, builder)


def logs(api: Api, mode: str = "bgl.kernel_panic", seed: int = 8) -> list[str]:
    scenario = api.builder.build(
        mode, seed=seed, nodes=4, duration_min=6, background_per_min=6, incident_per_min=8
    )
    return scenario.lines


async def wait_for(api: Api, run_id: str, *statuses: str, timeout_s: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while True:
        detail: dict[str, Any] = (await api.client.get(f"/api/v1/runs/{run_id}")).json()
        if detail["status"] in statuses:
            return detail
        if time.monotonic() > deadline:
            msg = f"run {run_id} stayed {detail['status']}"
            raise AssertionError(msg)
        await asyncio.sleep(0.05)


async def start(api: Api, **fields: Any) -> dict[str, Any]:
    body = {"system": "bgl", "title": "Kernel panics", "logs": logs(api), **fields}
    created = await api.client.post("/api/v1/runs", json=body)
    assert created.status_code == 202, created.text
    return await wait_for(api, created.json()["run_id"], "awaiting_review")


def sse(text: str) -> list[dict[str, Any]]:
    """Parse a server-sent-events body into {event, id, data} records."""
    out: list[dict[str, Any]] = []
    for block in text.split("\r\n\r\n" if "\r\n\r\n" in text else "\n\n"):
        record: dict[str, Any] = {}
        for line in block.splitlines():
            key, _, value = line.partition(":")
            if key in ("event", "id", "data"):
                record[key] = value.strip()
        if "data" in record:
            record["data"] = json.loads(record["data"])
            out.append(record)
    return out


# --- auth, limits and health ----------------------------------------------------------------------


async def test_health_is_public_and_everything_else_needs_a_key(api: Api) -> None:
    anonymous = {"Authorization": ""}
    assert (await api.client.get("/healthz", headers=anonymous)).json()["status"] == "ok"
    ready = (await api.client.get("/readyz", headers=anonymous)).json()
    assert (ready["database"], ready["incidents"], ready["runbooks"]) == (True, 3, 18)
    card = await api.client.get("/.well-known/agent-card.json", headers=anonymous)
    assert card.status_code == 200
    assert "bearer" in card.json()["securitySchemes"]
    for path in ("/api/v1/runs", "/metrics", "/api/v1/providers"):
        denied = await api.client.get(path, headers={"Authorization": "Bearer nope"})
        assert denied.status_code == 401
        assert denied.headers["www-authenticate"] == "Bearer"
    assert (await api.client.get("/api/v1/runs", headers=RAJ)).status_code == 200
    providers = (await api.client.get("/api/v1/providers")).json()
    assert {p["name"] for p in providers} >= {"nim", "fake"}
    assert "nvapi" not in json.dumps(providers)
    page = await api.client.get("/healthz")
    assert page.headers["x-content-type-options"] == "nosniff"


async def test_rate_limit_answers_429_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARIA_API_KEYS", "ana:k-ana")
    monkeypatch.setenv("ARIA_RATE_LIMIT_PER_MINUTE", "3")
    reset_caches()
    init_db(get_engine())
    app = create_app()
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost:8000") as c:
            codes = [(await c.get("/api/v1/runs", headers=ANA)).status_code for _ in range(4)]
            assert codes == [200, 200, 200, 429]
            limited = await c.get("/api/v1/runs", headers=ANA)
            assert int(limited.headers["retry-after"]) >= 1
            assert (await c.get("/healthz")).status_code == 200  # health is never limited


def test_production_refuses_to_start_without_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_caches()
    settings = get_settings().model_copy(update={"env": Environment.PROD, "api_keys": None})
    with pytest.raises(RuntimeError, match="ARIA_API_KEYS"):
        create_app(settings=settings)


# --- the run lifecycle ----------------------------------------------------------------------------


async def test_run_lifecycle_over_http(api: Api) -> None:
    detail = await start(api)
    run_id = detail["id"]
    assert detail["review"]["type"] == "review"
    assert detail["severity"] == detail["review"]["severity"]
    assert detail["latency_ms"] is not None

    events = (await api.client.get(f"/api/v1/runs/{run_id}/events")).json()
    assert [e["seq"] for e in events] == list(range(len(events)))
    streamed = await api.client.get(f"/api/v1/runs/{run_id}/stream", params={"until": "review"})
    records = sse(streamed.text)
    assert [int(r["id"]) for r in records] == [e["seq"] for e in events]
    resumed = await api.client.get(
        f"/api/v1/runs/{run_id}/stream",
        params={"until": "review"},
        headers={**ANA, "Last-Event-ID": str(events[5]["seq"])},
    )
    assert int(sse(resumed.text)[0]["id"]) == events[6]["seq"]

    state = (await api.client.get(f"/api/v1/runs/{run_id}/state")).json()
    assert state["values"]["request"]["logs"]["omitted"] is True
    assert state["next"] == ["review"]

    done = await api.client.post(f"/api/v1/runs/{run_id}/review", json={"decision": "approve"})
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "published"
    report = (await api.client.get(f"/api/v1/runs/{run_id}/report")).json()
    assert report["report"]["status"] == "published"
    review = next(e for e in report["report"]["evidence"] if e["kind"] == "review")
    assert review["data"]["reviewer"] == "ana"  # from the API key, not the request body
    markdown = await api.client.get(f"/api/v1/runs/{run_id}/report.md")
    assert markdown.headers["content-type"].startswith("text/markdown")
    postmortem = await api.client.get(f"/api/v1/runs/{run_id}/postmortem.md")
    assert postmortem.status_code == 200
    listed = (await api.client.get("/api/v1/runs", params={"status": "published"})).json()
    assert [r["id"] for r in listed["runs"]] == [run_id]

    history = (await api.client.get(f"/api/v1/runs/{run_id}/history")).json()
    before_review = next(h for h in history if h["next"] == ["review"])
    fork = await api.client.post(
        f"/api/v1/runs/{run_id}/fork", json={"checkpoint_id": before_review["checkpoint_id"]}
    )
    assert fork.status_code == 202
    forked = await wait_for(api, fork.json()["run_id"], "awaiting_review")
    assert forked["parent_run_id"] == run_id

    assert (await api.client.delete(f"/api/v1/runs/{run_id}")).status_code == 204
    assert (await api.client.get(f"/api/v1/runs/{run_id}")).status_code == 404
    metrics = (await api.client.get("/metrics")).text
    assert 'aria_runs{status="awaiting_review"} 1.0' in metrics
    assert "aria_time_to_review_seconds_count" in metrics


async def test_review_errors_are_reported_without_losing_the_pause(api: Api) -> None:
    run_id = (await start(api))["id"]
    unknown = await api.client.post(
        f"/api/v1/runs/{run_id}/review", json={"decision": "approve", "approve_actions": ["x"]}
    )
    assert unknown.status_code == 422
    assert "unknown action ids" in unknown.json()["detail"]
    bad = await api.client.post(f"/api/v1/runs/{run_id}/review", json={"decision": "maybe"})
    assert bad.status_code == 422
    assert (await api.client.get(f"/api/v1/runs/{run_id}")).json()["status"] == "awaiting_review"
    rejected = await api.client.post(
        f"/api/v1/runs/{run_id}/review", json={"decision": "reject", "comment": "dup"}
    )
    assert rejected.json()["status"] == "rejected"
    again = await api.client.post(f"/api/v1/runs/{run_id}/review", json={"decision": "approve"})
    assert again.status_code == 409
    bad_fork = await api.client.post(f"/api/v1/runs/{run_id}/fork", json={"checkpoint_id": "nope"})
    assert bad_fork.status_code in (404, 409)
    assert (await api.client.get("/api/v1/runs/run-missing/report")).status_code == 404


# --- alerts, Ask ARIA and the catalog -------------------------------------------------------------


def _alertmanager(group: str, *statuses: str) -> dict[str, Any]:
    alerts = [
        {
            "status": status,
            "labels": {"alertname": f"KernelPanic{i}", "severity": "critical", "job": "bgl"},
            "annotations": {"summary": "Kernel panics on compute nodes"},
            "startsAt": "2026-10-29T03:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": f"{group}-{i}",
        }
        for i, status in enumerate(statuses)
    ]
    return {
        "version": "4",
        "groupKey": group,
        "status": statuses[0],
        "commonLabels": {"job": "bgl", "severity": "critical"},
        "alerts": alerts,
    }


async def test_alert_storms_become_one_grouped_run(api: Api) -> None:
    first = (
        await api.client.post(
            "/api/v1/alerts/alertmanager", json=_alertmanager("g1", "firing", "firing")
        )
    ).json()
    assert (first["grouped"], first["alerts"]) == (False, 2)
    second = (
        await api.client.post("/api/v1/alerts/grafana", json=_alertmanager("g1", "firing"))
    ).json()
    assert second["grouped"] is True
    assert second["run_id"] == first["run_id"]
    detail = await wait_for(api, first["run_id"], "awaiting_review")
    assert detail["alert_group_id"] == first["alert_group_id"]
    assert detail["system"] == "bgl"
    resolved = (
        await api.client.post("/api/v1/alerts/alertmanager", json=_alertmanager("g2", "resolved"))
    ).json()
    assert (resolved["run_id"], resolved["status"]) == (None, "resolved")
    own = await api.client.post(
        "/api/v1/alerts", json=[{"name": "DiskFull", "fingerprint": "d1", "labels": {"job": "x"}}]
    )
    assert own.status_code == 202
    empty = await api.client.post("/api/v1/alerts/alertmanager", json={"alerts": []})
    assert empty.status_code == 422


async def test_ask_cites_run_evidence(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = (await start(api))["id"]
    retrieval = (
        await api.client.post(
            "/api/v1/ask", json={"question": "Which kernel errors happened?", "run_id": run_id}
        )
    ).json()
    assert retrieval["answered_by"] == "retrieval"
    assert retrieval["answer"]
    cited = {e["id"] for e in retrieval["evidence"]}
    assert all(set(a["evidence_ids"]) <= cited for a in retrieval["answer"])

    monkeypatch.setattr(api.state.services.router, "has_real_llm", lambda role: True)
    llm = (
        await api.client.post(
            "/api/v1/ask", json={"question": "Which kernel errors happened?", "run_id": run_id}
        )
    ).json()
    assert llm["answered_by"] == "llm"
    assert llm["model"]
    memory = (
        await api.client.post("/api/v1/ask", json={"question": "brute force ssh logins"})
    ).json()
    assert memory["evidence"]
    assert any("openssh" in e["title"] for e in memory["evidence"])
    nothing = (await api.client.post("/api/v1/ask", json={"question": "zzzqqq wwwxxx"})).json()
    assert nothing["insufficient_evidence"] is True
    missing = await api.client.post("/api/v1/ask", json={"question": "why?", "run_id": "run-nope"})
    assert missing.status_code == 404


async def test_catalog_lists_incidents_and_runbooks(api: Api) -> None:
    found = (await api.client.get("/api/v1/incidents", params={"q": "kernel panic"})).json()
    assert found[0]["system"] == "bgl"
    one = await api.client.get(f"/api/v1/incidents/{found[0]['incident_id']}")
    assert one.json()["synthetic"] is True
    assert (await api.client.get("/api/v1/incidents/nope")).status_code == 404
    recent = (await api.client.get("/api/v1/incidents", params={"system": "hdfs"})).json()
    assert [i["system"] for i in recent] == ["hdfs"]
    runbooks = (await api.client.get("/api/v1/runbooks", params={"system": "zookeeper"})).json()
    slugs = {r["slug"] for r in runbooks}
    assert {"zookeeper-quorum-loss", "generic-triage"} <= slugs
    detail = (await api.client.get("/api/v1/runbooks/zookeeper-quorum-loss")).json()
    assert detail["risk"] == "high"
    text = await api.client.get("/api/v1/runbooks/zookeeper-quorum-loss.md")
    assert text.text.startswith("# ")
    assert (await api.client.get("/api/v1/runbooks/nope")).status_code == 404


# --- agent protocols ------------------------------------------------------------------------------


async def test_a2a_task_pauses_for_review_and_completes(api: Api) -> None:
    card = (await api.client.get("/.well-known/agent-card.json")).json()
    assert card["skills"][0]["id"] == "incident-triage"
    assert card["supportedInterfaces"][0]["url"].endswith("/a2a")
    message = {
        "messageId": "m1",
        "role": "ROLE_USER",
        "parts": [{"text": "\n".join(logs(api))}],
        "metadata": {"system": "bgl"},
    }
    headers = {**ANA, "A2A-Version": "1.0"}
    rpc = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": message}}
    task = (await api.client.post("/a2a", json=rpc, headers=headers)).json()["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    report = task["artifacts"][0]["parts"][0]["data"]
    assert report["severity"].startswith("SEV")
    assert "BlueGene/L" in report["title"]
    reply = {
        "messageId": "m2",
        "role": "ROLE_USER",
        "taskId": task["id"],
        "contextId": task["contextId"],
        "parts": [{"text": "maybe"}],
    }
    rpc = {"jsonrpc": "2.0", "id": 2, "method": "SendMessage", "params": {"message": reply}}
    asked = (await api.client.post("/a2a", json=rpc, headers=headers)).json()["result"]["task"]
    assert asked["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    reply["parts"] = [{"data": {"decision": "approve"}}]
    reply["messageId"] = "m3"
    rpc = {"jsonrpc": "2.0", "id": 3, "method": "SendMessage", "params": {"message": reply}}
    done = (await api.client.post("/a2a", json=rpc, headers=headers)).json()["result"]["task"]
    assert done["status"]["state"] == "TASK_STATE_COMPLETED"
    run = repo.get_run(api.state.services.engine, f"a2a-{task['id']}")
    assert run is not None
    assert run["status"] == "published"


async def test_agui_streams_a_run_and_resumes_its_interrupt(api: Api) -> None:
    body = {
        "threadId": "thread-ui-1",
        "runId": "ui-run-1",
        "messages": [{"id": "u1", "role": "user", "content": "\n".join(logs(api))}],
        "forwardedProps": {"system": "bgl"},
    }
    first = sse((await api.client.post("/agui", json=body)).text)
    types = [r["data"]["type"] for r in first]
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_FINISHED"
    assert types.count("STEP_STARTED") == types.count("STEP_FINISHED")
    for kind in ("TOOL_CALL_START", "TOOL_CALL_RESULT", "TEXT_MESSAGE_CONTENT", "STATE_SNAPSHOT"):
        assert kind in types
    state = next(r["data"] for r in first if r["data"]["type"] == "STATE_SNAPSHOT")["snapshot"]
    assert state["status"] == "awaiting_review"
    outcome = first[-1]["data"]["outcome"]
    assert outcome["type"] == "interrupt"
    interrupt = outcome["interrupts"][0]
    assert interrupt["reason"] == "review"
    assert "decision" in interrupt["responseSchema"]["properties"]

    stale = {**body, "runId": "ui-run-2", "resume": [{"interruptId": "x", "status": "resolved"}]}
    errored = sse((await api.client.post("/agui", json=stale)).text)
    assert errored[-1]["data"]["type"] == "RUN_ERROR"
    assert errored[-1]["data"]["code"] == "stale_interrupt"

    resume = {
        "threadId": "thread-ui-1",
        "runId": "ui-run-3",
        "messages": [],
        "resume": [
            {
                "interruptId": interrupt["id"],
                "status": "resolved",
                "payload": {"decision": "approve"},
            }
        ],
    }
    second = sse((await api.client.post("/agui", json=resume)).text)
    finished = second[-1]["data"]
    assert finished["type"] == "RUN_FINISHED"
    assert finished["outcome"]["type"] == "success"
    assert finished["result"]["status"] == "published"
    assert (await api.client.post("/agui", json={"bad": True})).status_code == 422


# --- real servers ---------------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def _wait_until(predicate: Callable[[], bool], timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)


async def test_mcp_and_live_sse_over_a_real_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARIA_API_KEYS", "ana:k-ana")
    reset_caches()
    builder = await _seed()
    dispose_engines()  # the server thread opens its own connections
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    await asyncio.to_thread(_wait_until, lambda: bool(server.started), 30)
    base = f"http://127.0.0.1:{port}"
    try:
        async with Client(remote_target(f"{base}/mcp", "k-ana"), read_timeout_seconds=30) as mcp:
            names = {tool.name for tool in (await mcp.list_tools()).tools}
            assert names == set(TOOL_NAMES)
        with pytest.raises(Exception):  # noqa: B017, PT011 - the transport's error type is internal
            async with Client(
                remote_target(f"{base}/mcp", "wrong"), read_timeout_seconds=10
            ) as bad:
                await bad.list_tools()

        lines = builder.build("bgl.kernel_panic", seed=8, nodes=4, duration_min=6).lines
        async with httpx.AsyncClient(base_url=base, headers=ANA, timeout=60) as client:
            created = await client.post("/api/v1/runs", json={"system": "bgl", "logs": lines})
            run_id = created.json()["run_id"]
            kinds: list[str] = []
            async with client.stream("GET", f"/api/v1/runs/{run_id}/stream") as stream:
                async for line in stream.aiter_lines():
                    if line.startswith("event:"):
                        kinds.append(line.split(":", 1)[1].strip())
                        if kinds[-1] == "interrupt":
                            break
            assert {"run_started", "node_started", "token", "interrupt"} <= set(kinds)
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 15)


async def test_external_worker_claims_and_runs_queued_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARIA_WORKER_MODE", "external")
    reset_caches()
    builder = await _seed()
    services = await Services.create()
    app = create_app(services=services)
    try:
        async with LifespanManager(app) as manager:
            transport = httpx.ASGITransport(app=manager.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://localhost:8000"
            ) as c:
                lines = builder.build("bgl.kernel_panic", seed=8, nodes=4, duration_min=6).lines
                run_id = (
                    await c.post("/api/v1/runs", json={"system": "bgl", "logs": lines})
                ).json()["run_id"]
                await asyncio.sleep(0.2)
                assert (await c.get(f"/api/v1/runs/{run_id}")).json()["status"] == "queued"
                state: AppState = app.state.aria
                stop = asyncio.Event()
                loop = asyncio.create_task(poll_forever(state.runner, interval_s=0.05, stop=stop))
                deadline = time.monotonic() + 30
                while (await c.get(f"/api/v1/runs/{run_id}")).json()["status"] != "awaiting_review":
                    assert time.monotonic() < deadline
                    await asyncio.sleep(0.05)
                stop.set()
                await loop
                assert repo.claim_runs(services.engine, "other-worker") == []
    finally:
        await services.aclose()


async def test_unfinished_runs_continue_after_a_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_caches()
    builder = await _seed()
    services = await Services.create()
    lines = builder.build("bgl.kernel_panic", seed=8, nodes=4, duration_min=6).lines
    run_id = TriageRunner(services).submit(TriageRequest(system="bgl", logs=lines))
    app = create_app(services=services)
    try:
        async with LifespanManager(app) as manager:
            transport = httpx.ASGITransport(app=manager.app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://localhost:8000"
            ) as c:
                deadline = time.monotonic() + 30
                while (await c.get(f"/api/v1/runs/{run_id}")).json()["status"] != "awaiting_review":
                    assert time.monotonic() < deadline
                    await asyncio.sleep(0.05)
    finally:
        await services.aclose()


async def test_worker_heartbeat_follows_its_polls(tmp_path: Path) -> None:
    reset_caches()
    init_db(get_engine())
    services = await Services.create()
    beat = tmp_path / "worker.heartbeat"
    assert heartbeat_age(beat) is None
    stop = asyncio.Event()
    task = asyncio.create_task(
        poll_forever(TriageRunner(services), interval_s=0.01, stop=stop, heartbeat=beat)
    )
    try:
        deadline = time.monotonic() + 10
        while heartbeat_age(beat) is None:
            assert time.monotonic() < deadline
            await asyncio.sleep(0.01)
    finally:
        stop.set()
        await task
        await services.aclose()
    age = heartbeat_age(beat)
    assert age is not None
    assert age < 5
