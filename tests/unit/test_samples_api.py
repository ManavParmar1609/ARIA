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
from aria.config import get_app_config, reset_caches
from aria.data.scenarios import SampleSizes, SizeChoice
from aria.db import repository as repo
from aria.db.engine import get_engine, init_db
from aria.graph.store import SqlStore
from aria.retrieval.seed import seed_known_templates
from aria.security.injection import scan
from aria.severity.samples import RunRating


@pytest.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setenv("ARIA_RATE_LIMIT_PER_MINUTE", "100000")
    reset_caches()
    # Sizes by the samples' labels, whatever `aria seed` saved on this machine.
    monkeypatch.setattr(samples, "saved_sizes", lambda *_: None)
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
    assert hdfs["rate"]["question"] == "How fast do the problem lines come?"
    assert hdfs["rate"]["options"][-1]["label"].endswith(" lines a minute")


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
    assert stored["request"]["sample"] == {"id": "openssh.bruteforce", "servers": 24, "rate": None}
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


async def test_only_the_samples_endpoint_may_say_a_run_is_a_sample(
    client: httpx.AsyncClient,
) -> None:
    body = {
        "system": "openssh",
        "logs": ["Failed password for root from 203.0.113.9 port 22 ssh2"],
        "sample": {"id": "openssh.bruteforce", "servers": 24},
    }
    created = await client.post("/api/v1/runs", json=body)
    assert created.status_code == 202, created.text
    state: AppState = client.app_state  # type: ignore[attr-defined]
    stored = repo.get_run(state.services.engine, created.json()["run_id"])
    assert stored is not None
    assert stored["request"]["sample"] is None
    default = await client.post(
        "/api/v1/scenarios/hdfs.block_serve_exceptions/runs", json={"options": {"use_llm": False}}
    )
    made = repo.get_run(state.services.engine, default.json()["run_id"])
    assert made is not None
    assert made["request"]["sample"] == {
        "id": "hdfs.block_serve_exceptions",
        "servers": None,  # HDFS logs name no servers, so there is no size to record
        "rate": 12,
    }


async def test_a_sample_is_rated_the_way_its_run_rates_it(client: httpx.AsyncClient) -> None:
    state: AppState = client.app_state  # type: ignore[attr-defined]
    builder = samples._builder()
    # The routine templates `aria seed` stores, which a run judges "novel" against.
    await seed_known_templates(SqlStore(state.services.engine), builder, systems=["linux"])
    rating = RunRating(builder, state.services.severity, get_app_config().guardrails)
    for servers in builder.sample_sizes("linux.auth_failures").servers.values:  # type: ignore[union-attr]
        created = await client.post(
            "/api/v1/scenarios/linux.auth_failures/runs",
            json={"servers": servers, "options": {"use_llm": False}},
        )
        detail = await _wait(client, created.json()["run_id"])
        expected = rating(builder.sample("linux.auth_failures", servers=servers))
        assert detail["severity"] == str(expected), servers


async def test_the_samples_offer_the_sizes_seed_rated(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    rated = {"openssh.bruteforce": SampleSizes(SizeChoice((2, 8, 16)), None)}
    monkeypatch.setattr(samples, "saved_sizes", lambda *_: rated)
    samples._builder.cache_clear()
    listed = (await client.get("/api/v1/scenarios")).json()
    ssh = next(s for s in listed if s["id"] == "openssh.bruteforce")
    assert [o["value"] for o in ssh["servers"]["options"]] == [2, 8, 16]
    refused = await client.post("/api/v1/scenarios/openssh.bruteforce/runs", json={"servers": 6})
    assert refused.status_code == 422
    assert "Choose the number of servers from 2, 8 or 16." in refused.json()["detail"]
