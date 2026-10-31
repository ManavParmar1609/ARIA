"""Samples built on the server: the list, sizes that change the result, and starting a run."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from asgi_lifespan import LifespanManager

from aria.api.app import create_app
from aria.api.routers import scenarios as samples
from aria.api.state import AppState
from aria.config import reset_caches
from aria.db import repository as repo
from aria.db.engine import get_engine, init_db
from aria.security.injection import scan


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("ARIA_RATE_LIMIT_PER_MINUTE", "100000")
    reset_caches()
    samples._builder.cache_clear()
    init_db(get_engine())
    app = create_app()
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:8000", timeout=60
        ) as c:
            c.app_state = app.state.aria  # type: ignore[attr-defined]
            yield c


async def _wait(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while True:
        detail: dict[str, Any] = (await client.get(f"/api/v1/runs/{run_id}")).json()
        if detail["status"] in ("awaiting_review", "failed"):
            return detail
        assert time.monotonic() < deadline, f"run {run_id} stayed {detail['status']}"
        await asyncio.sleep(0.05)


async def test_the_samples_are_listed_by_where_their_logs_come_from(
    client: httpx.AsyncClient,
) -> None:
    listed = (await client.get("/api/v1/scenarios")).json()
    assert len(listed) == 21
    sources = [s["source"] for s in listed]
    assert sources == sorted(sources, key=["security", "web", "bigdata", "hpc", "noise"].index)
    ssh = next(s for s in listed if s["id"] == "openssh.bruteforce")
    assert (ssh["title"], ssh["technology"]) == ("Someone keeps guessing passwords", "OpenSSH")
    assert ssh["source_name"] == "Security and sign-ins"
    assert ssh["tricky"] is True
    assert ssh["servers"]["question"] == "How many servers?"
    assert [o["value"] for o in ssh["servers"]["options"]] == [2, 6, 24]
    assert ssh["servers"]["options"][0]["label"] == "2 servers"
    assert ssh["rate"] is None
    assert len(ssh["preview"]) == 3
    noise = [s for s in listed if s["source"] == "noise"]
    assert all(s["benign"] and s["servers"] is None and s["rate"] is None for s in noise)
    hdfs = next(s for s in listed if s["id"] == "hdfs.block_serve_exceptions")
    assert hdfs["servers"] is None  # HDFS logs name no servers
    assert hdfs["rate"]["question"] == "How fast?"
    assert hdfs["rate"]["options"][-1]["label"].endswith(" a minute")


async def test_a_sample_starts_as_a_run_at_the_size_asked_for(client: httpx.AsyncClient) -> None:
    state: AppState = client.app_state  # type: ignore[attr-defined]
    created = await client.post(
        "/api/v1/scenarios/openssh.bruteforce/runs",
        json={"servers": 24, "options": {"use_llm": False}},
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["run_id"]
    detail = await _wait(client, run_id)
    assert detail["status"] == "awaiting_review"
    assert detail["trigger"] == "sample"
    stored = repo.get_run(state.services.engine, run_id)
    assert stored is not None
    assert stored["request"]["synthetic"] is True
    lines = stored["request"]["logs"]
    assert lines == samples._builder().sample("openssh.bruteforce", servers=24).lines
    # The line that tries to talk ARIA out of the incident is caught, not obeyed.
    assert scan(lines)
    values = (await client.get(f"/api/v1/runs/{run_id}/state")).json()["values"]
    assert len(values["batch"]["guard"]["injections"]) == 1  # quarantined, kept from any model


async def test_a_size_must_be_one_the_sample_offers(client: httpx.AsyncClient) -> None:
    for scenario_id, body, problem in (
        ("openssh.bruteforce", {"servers": 7}, "Choose the number of servers from 2, 6 or 24."),
        ("openssh.bruteforce", {"rate": 30}, "This sample has no rate to choose"),
        ("mac.cocoa_scripting_noise", {"servers": 6}, "no number of servers to choose"),
    ):
        refused = await client.post(f"/api/v1/scenarios/{scenario_id}/runs", json=body)
        assert refused.status_code == 422, body
        assert problem in refused.json()["detail"]
    missing = await client.post("/api/v1/scenarios/no.such_sample/runs", json={})
    assert missing.status_code == 404
    odd = await client.post("/api/v1/scenarios/openssh.bruteforce/runs", json={"nodes": 3})
    assert odd.status_code == 422  # unknown fields are refused, not ignored
