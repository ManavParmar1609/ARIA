"""Prometheus metrics: event counters fed by the runner, and run counts read at scrape time."""

from __future__ import annotations

from collections.abc import Iterator

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from aria import __version__
from aria.contracts.run import RunEvent
from aria.db.engine import session_scope
from aria.db.models import RunRow

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


class RunsCollector(Collector):
    """``aria_runs{status}``: how many runs are in each state, read from the database."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def collect(self) -> Iterator[GaugeMetricFamily]:
        family = GaugeMetricFamily("aria_runs", "Runs by status", labels=["status"])
        with session_scope(self.engine) as session:
            rows = session.execute(select(RunRow.status, func.count()).group_by(RunRow.status))
            for status, count in rows:
                family.add_metric([str(status)], float(count))
        yield family


class Metrics:
    def __init__(self, engine: Engine) -> None:
        self.registry = CollectorRegistry()
        self.events = Counter(
            "aria_run_events", "Run events by kind", ["kind"], registry=self.registry
        )
        self.finished = Counter(
            "aria_runs_finished",
            "Runs that reached a final state",
            ["status"],
            registry=self.registry,
        )
        self.tool_calls = Counter(
            "aria_tool_calls", "Investigator tool calls", ["tool"], registry=self.registry
        )
        self.reviews = Counter(
            "aria_reviews", "Review decisions", ["decision"], registry=self.registry
        )
        self.time_to_review = Histogram(
            "aria_time_to_review_seconds",
            "From run start until the report is ready for review",
            buckets=(5, 10, 20, 30, 60, 90, 120, 180, 300, 600),
            registry=self.registry,
        )
        info = Gauge("aria_info", "Build information", ["version"], registry=self.registry)
        info.labels(__version__).set(1)
        self.registry.register(RunsCollector(engine))

    def observe(self, event: RunEvent) -> None:
        self.events.labels(event.kind).inc()
        if event.kind == "run_finished":
            self.finished.labels(str(event.payload.get("status", "unknown"))).inc()
        elif event.kind == "tool_call" and event.payload.get("phase") != "result":
            self.tool_calls.labels(str(event.payload.get("tool", "unknown"))).inc()
        elif event.kind == "review":
            self.reviews.labels(str(event.payload.get("decision", "unknown"))).inc()
        elif event.kind == "budget" and "latency_ms" in event.payload:
            self.time_to_review.observe(float(event.payload["latency_ms"]) / 1_000)

    def render(self) -> bytes:
        return generate_latest(self.registry)
