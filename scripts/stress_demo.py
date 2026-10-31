"""Stress a running ARIA API the way a shared public demo gets used.

    uv run python -I scripts/stress_demo.py --base http://127.0.0.1:8000 --visitors 12

Each simulated visitor has a private session of its own (``X-Visitor-Id``, as the console sends
it). It lists the samples, starts one, follows it until it waits for review, asks a question
about it, reads its settings and incident list, then approves or discards the incident. Around
them, the script sends what a careless or hostile caller would: empty, malformed and oversized
bodies, unknown ids, someone else's incident, and the same sample started twice at once (a double
click).

It prints the answers by status and the time each kind of request took, then every answer that
was not the expected one. It exits with 1 if any request failed with a server error (5xx), was
refused for a reason other than load, or broke a visitor's privacy.

Runs are started offline (``use_llm: false``). If the server says it has a model key of its own,
the script stops unless ``--allow-model`` is given: every visitor would spend that key's
allowance.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import httpx

FINISHED = {"awaiting_review", "published", "rejected", "failed"}
QUESTIONS = ["What failed first?", "Which component is affected?", "How was this fixed before?"]


@dataclass
class Tally:
    """Every answer, by endpoint and status, with the time it took and anything unexpected."""

    statuses: Counter[tuple[str, int]] = field(default_factory=Counter)
    timings: defaultdict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    problems: list[str] = field(default_factory=list)
    busy: int = 0
    ahead_seen: int = 0

    def record(self, name: str, response: httpx.Response, started: float) -> None:
        self.statuses[(name, response.status_code)] += 1
        self.timings[name].append(time.monotonic() - started)
        if response.status_code == 429:
            self.busy += 1
        elif response.status_code >= 500:
            self.problems.append(f"{name}: {response.status_code} {response.text[:200]}")

    def expect(self, name: str, response: httpx.Response, *wanted: int) -> bool:
        if response.status_code in wanted or response.status_code == 429:
            return response.status_code in wanted
        if response.status_code < 500:  # a 5xx is already a problem
            self.problems.append(
                f"{name}: wanted {' or '.join(map(str, wanted))}, got {response.status_code} "
                f"{response.text[:200]}"
            )
        return False


async def call(
    client: httpx.AsyncClient,
    tally: Tally,
    name: str,
    method: str,
    path: str,
    *,
    visitor: str | None = None,
    retries: int = 3,
    **kwargs: Any,
) -> httpx.Response:
    """One request, retried after the server's Retry-After when it is busy (as a person would)."""
    headers = {"x-visitor-id": visitor} if visitor else {}
    for attempt in range(retries + 1):
        started = time.monotonic()
        response = await client.request(method, path, headers=headers, **kwargs)
        tally.record(name, response, started)
        if response.status_code != 429 or attempt == retries:
            return response
        await asyncio.sleep(min(10.0, float(response.headers.get("retry-after", "1"))))
    return response


async def visit(
    client: httpx.AsyncClient, tally: Tally, number: int, samples: list[str], timeout_s: float
) -> str | None:
    """One visitor's session; returns their incident id, for the privacy check."""
    visitor = f"stress-{uuid.uuid4()}"
    rng = random.Random(number)  # noqa: S311 - choosing what a visitor does, not a secret
    await asyncio.sleep(rng.random() * 2)  # visitors arrive over a couple of seconds
    response = await call(client, tally, "settings", "GET", "/api/v1/settings", visitor=visitor)
    tally.expect("settings", response, 200)
    sample = rng.choice(samples)
    response = await call(
        client,
        tally,
        "start sample",
        "POST",
        f"/api/v1/scenarios/{sample}/runs",
        visitor=visitor,
        json={"options": {"use_llm": False, "investigate": True, "require_approval": True}},
    )
    if not tally.expect("start sample", response, 202):
        return None
    run_id = str(response.json()["run_id"])
    deadline = time.monotonic() + timeout_s
    status = "queued"
    while status not in FINISHED:
        if time.monotonic() > deadline:
            tally.problems.append(f"{run_id}: still {status} after {timeout_s:.0f} s")
            return run_id
        await asyncio.sleep(1.5)
        response = await call(
            client, tally, "follow run", "GET", f"/api/v1/runs/{run_id}", visitor=visitor
        )
        if not tally.expect("follow run", response, 200):
            continue
        detail = response.json()
        status = detail["status"]
        if status == "queued" and detail.get("ahead"):
            tally.ahead_seen += 1
    if status == "failed":
        tally.problems.append(f"{run_id}: the run failed: {detail.get('error')}")
        return run_id
    response = await call(
        client,
        tally,
        "ask",
        "POST",
        "/api/v1/ask",
        visitor=visitor,
        json={"question": rng.choice(QUESTIONS), "run_id": run_id},
    )
    tally.expect("ask", response, 200)
    response = await call(
        client, tally, "list runs", "GET", "/api/v1/runs?limit=50", visitor=visitor
    )
    if tally.expect("list runs", response, 200):
        mine = {r["id"] for r in response.json()["runs"] if not r.get("example")}
        if mine - {run_id}:
            tally.problems.append(f"visitor {number} sees incidents that aren't theirs: {mine}")
    if status == "awaiting_review":
        decision = rng.choice(["approve", "reject"])
        response = await call(
            client,
            tally,
            "review",
            "POST",
            f"/api/v1/runs/{run_id}/review",
            visitor=visitor,
            json={"decision": decision, "reviewer": f"stress {number}"},
        )
        tally.expect("review", response, 200)
    return run_id


async def abuse(client: httpx.AsyncClient, tally: Tally, sample: str, max_mb: int) -> None:
    """What a careless or hostile caller sends: each must get a clear 4xx, never a 5xx."""
    visitor = f"stress-{uuid.uuid4()}"
    cases: list[tuple[str, str, str, dict[str, Any], tuple[int, ...]]] = [
        ("empty logs", "POST", "/api/v1/runs", {"json": {"system": "hdfs", "logs": []}}, (422,)),
        (
            "malformed json",
            "POST",
            "/api/v1/runs",
            {"content": b"{not json", "headers": {"content-type": "application/json"}},
            (422,),
        ),
        (
            "oversized body",
            "POST",
            "/api/v1/runs",
            {"json": {"system": "hdfs", "logs": ["x" * 1024] * (max_mb * 1024 + 64)}},
            (413,),
        ),
        ("unknown run", "GET", "/api/v1/runs/run-20200101-0000000000", {}, (404,)),
        ("unknown sample", "POST", "/api/v1/scenarios/no.such.sample/runs", {}, (404,)),
        ("bad size", "POST", f"/api/v1/scenarios/{sample}/runs", {"json": {"rate": 999}}, (422,)),
        ("short question", "POST", "/api/v1/ask", {"json": {"question": "?"}}, (422,)),
    ]
    for name, method, path, kwargs, wanted in cases:
        headers = {"x-visitor-id": visitor, **kwargs.pop("headers", {})}
        started = time.monotonic()
        response = await client.request(method, path, headers=headers, **kwargs)
        tally.record(name, response, started)
        tally.expect(name, response, *wanted)
    # A double click: the same sample started twice at once. Both are accepted, as two incidents.
    body = {"options": {"use_llm": False, "investigate": False, "require_approval": True}}
    twice = await asyncio.gather(
        *(
            call(
                client,
                tally,
                "double click",
                "POST",
                f"/api/v1/scenarios/{sample}/runs",
                visitor=visitor,
                json=body,
            )
            for _ in range(2)
        )
    )
    for response in twice:
        tally.expect("double click", response, 202)


async def privacy(client: httpx.AsyncClient, tally: Tally, run_id: str) -> None:
    """Another visitor must not read someone's incident."""
    response = await call(
        client,
        tally,
        "someone else's run",
        "GET",
        f"/api/v1/runs/{run_id}",
        visitor=f"stress-{uuid.uuid4()}",
    )
    if response.status_code == 200 and not response.json().get("example"):
        tally.problems.append(f"another visitor could read {run_id}")


def report(tally: Tally, elapsed: float) -> None:
    print(f"\nfinished in {elapsed:.1f} s")
    print("\nanswers:")
    for (name, status), n in sorted(tally.statuses.items()):
        print(f"  {name:<20} {status}  x{n}")
    print("\ntime taken (median / slowest, seconds):")
    for name, times in sorted(tally.timings.items()):
        print(f"  {name:<20} {statistics.median(times):6.2f} / {max(times):6.2f}")
    print(f"\nbusy answers (429, retried): {tally.busy}")
    print(f"times a queued incident said how many triages were ahead: {tally.ahead_seen}")
    if tally.problems:
        print(f"\n{len(tally.problems)} problems:")
        for problem in tally.problems:
            print(f"  - {problem}")
    else:
        print("\nno problems")


async def main(args: argparse.Namespace) -> int:
    tally = Tally()
    limits = httpx.Limits(max_connections=args.visitors * 2 + 8)
    async with httpx.AsyncClient(base_url=args.base, timeout=60.0, limits=limits) as client:
        settings = (await client.get("/api/v1/settings")).json()
        if settings.get("shared_model") and not args.allow_model:
            print(
                "This server has a model key of its own, and every visitor would spend its "
                "allowance. Pass --allow-model to go ahead anyway.",
                file=sys.stderr,
            )
            return 2
        max_mb = max(1, int(settings.get("max_body_bytes", 8 * 1024 * 1024)) // (1024 * 1024))
        samples = [s["id"] for s in (await client.get("/api/v1/scenarios")).json()]
        if not samples:
            print("This server offers no samples.", file=sys.stderr)
            return 2
        started = time.monotonic()
        runs, _ = await asyncio.gather(
            asyncio.gather(
                *(visit(client, tally, n, samples, args.timeout) for n in range(args.visitors))
            ),
            abuse(client, tally, samples[0], max_mb),
        )
        for run_id in [r for r in runs if r][:3]:
            await privacy(client, tally, run_id)
        report(tally, time.monotonic() - started)
    return 1 if tally.problems else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="http://127.0.0.1:8000", help="the ARIA API's address")
    parser.add_argument("--visitors", type=int, default=12, help="visitors at once")
    parser.add_argument(
        "--timeout", type=float, default=300.0, help="seconds a visitor waits for their run"
    )
    parser.add_argument(
        "--allow-model", action="store_true", help="go ahead even if the server has a model key"
    )
    sys.exit(asyncio.run(main(parser.parse_args())))
