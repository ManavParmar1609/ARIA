"""ITBench-Lite's site-reliability scenarios (IBM Research): snapshots of a Kubernetes cluster
running the OpenTelemetry demo shop while a fault was injected.

Each scenario holds the Prometheus alerts in alerting state when the incident was raised, the
cluster's Kubernetes events, the services' OpenTelemetry logs, and a ground truth naming the
entity at fault, how the fault spread, and the alerts it should raise. ARIA reads what an
on-call engineer would be paged with: the alerts in alerting state, the Kubernetes events, and
the services' logs from the minutes before the incident was raised. The ground truth stays out
of anything ARIA reads.

The logs are large (about 4 GB over the 35 scenarios), so ``aria data download`` streams each
scenario's ``otel_logs_raw.tsv``, checks it against the sha256 the Hub records for it, and keeps
only the lines from the ``minutes`` before the incident, at most ``limit`` of them (the newest),
in ``logs_window.tsv.gz`` beside the scenario's other files.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import yaml

from aria.contracts.inputs import AlertSignal
from aria.data.loghub import normalize_level
from aria.data.manifest import DataSource

ITBENCH_DIR = Path("data/raw/itbench-lite")
ITBENCH_CITATION = (
    "S. Jha et al. ITBench: Evaluating AI Agents across Diverse Real-World IT Automation Tasks. "
    "ICML 2025. Data: IBM Research, ITBench-Lite, huggingface.co/datasets/ibm-research/ITBench-Lite."
)
WINDOW_FILE = "logs_window.tsv.gz"
WINDOW_COLUMNS = ("ts", "service", "pod", "severity", "body")
_STATE_FILE = re.compile(r"alerts_in_alerting_state_(\d{4}-\d{2}-\d{2}T\d{6}\.\d+)Z\.json$")
_AT_FILE = re.compile(r"alerts_at_(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}\.\d+)\.json$")
_POD = re.compile(r"'k8s\.pod\.name': '([^']*)'")
# A pod's name is its workload's plus a ReplicaSet hash and a suffix: frontend-675fd7b5c5-jlpzp.
_POD_SUFFIX = re.compile(r"-[0-9a-f]{6,10}-[0-9a-z]{5}$")
_REPLICASET_SUFFIX = re.compile(r"-[0-9a-f]{6,10}$")
_ORDINAL = re.compile(r"-\d+$")
# Workload kinds whose name is a service's; a fault elsewhere (a ConfigMap, a namespace quota,
# an autoscaler) is localised by the first workloads it spreads to.
WORKLOADS = {"Pod", "Service", "Deployment", "ReplicaSet", "StatefulSet", "DaemonSet"}
MAX_FIELD = 16 << 20
# OpenTelemetry severity texts that are not log levels ARIA knows (.NET writes "Information").
_OTEL_LEVELS = {"information": "INFO", "critical": "FATAL"}


@dataclass(frozen=True)
class Scenario:
    id: str  # "Scenario-1"
    directory: Path
    raised_at: datetime | None  # when the incident was raised: the alerts-in-alerting-state time
    root_kinds: tuple[str, ...]  # kinds of the entities marked as the root cause
    categories: tuple[str, ...]  # the fault's category, e.g. "Resource Unavailable"
    services: tuple[str, ...]  # the services ARIA should name: see services_at_fault
    alert_services: tuple[str, ...] = field(default=())  # services the expected alerts are on


def workload(name: str) -> str:
    """The workload a pod or ReplicaSet belongs to: 'frontend-675fd7b5c5-jlpzp' -> 'frontend'."""
    name = name.strip().lower()
    for pattern in (_POD_SUFFIX, _REPLICASET_SUFFIX):
        stripped = pattern.sub("", name)
        if stripped != name:
            return stripped
    return name


def _group_name(group: Mapping[str, Any]) -> str:
    """'frontend-proxy\\b' or 'ad-.*' in a group's filter -> 'frontend-proxy' or 'ad'."""
    filters = group.get("filter") or []
    raw = str(filters[0]) if filters else str(group.get("name") or group.get("id") or "")
    name = re.sub(r"\\b|\.\*|\$|\^|\\", "", raw).strip("-. ")
    return _ORDINAL.sub("", name) if not filters else name


def services_at_fault(truth: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(services ARIA should name, kinds of the root-cause entities).

    The services of root-cause groups that are workloads; when the root cause is not a workload,
    the workloads it spreads to first (the targets of its propagations)."""
    groups = {str(g.get("id")): g for g in truth.get("groups") or [] if isinstance(g, Mapping)}
    roots = [g for g in groups.values() if g.get("root_cause")]
    kinds = tuple(sorted({str(g.get("kind") or "") for g in roots}))
    names = {_group_name(g) for g in roots if g.get("kind") in WORKLOADS}
    if not names:
        root_ids = {str(g.get("id")) for g in roots}
        for hop in truth.get("propagations") or []:
            target = groups.get(str(hop.get("target")))
            if str(hop.get("source")) in root_ids and target and target.get("kind") in WORKLOADS:
                names.add(_group_name(target))
    return tuple(sorted(n for n in names if n)), kinds


def _raised_at(directory: Path) -> datetime | None:
    for path in sorted(directory.rglob("alerts_in_alerting_state_*.json")):
        found = _STATE_FILE.search(path.name)
        if found:
            return datetime.strptime(found.group(1), "%Y-%m-%dT%H%M%S.%f").replace(tzinfo=UTC)
    return None


def ground_truth(path: Path) -> dict[str, Any]:
    """A scenario's ground truth. Some files wrap it as a Kubernetes object, under ``spec``."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        return {}
    spec = raw.get("spec")
    return dict(spec) if isinstance(spec, Mapping) else dict(raw)


def find_scenarios(root: Path = ITBENCH_DIR) -> list[Scenario]:
    """Every downloaded SRE scenario with a ground truth, by scenario number."""
    out: list[Scenario] = []
    for truth_path in root.glob("snapshots/sre/*/Scenario-*/ground_truth.yaml"):
        directory = truth_path.parent
        truth = ground_truth(truth_path)
        services, kinds = services_at_fault(truth)
        groups = {str(g.get("id")): g for g in truth.get("groups") or [] if isinstance(g, Mapping)}
        alert_services = {
            _group_name(groups[str(a.get("group_id"))])
            for a in truth.get("alerts") or []
            if str(a.get("group_id")) in groups
        }
        out.append(
            Scenario(
                id=directory.name,
                directory=directory,
                raised_at=_raised_at(directory),
                root_kinds=kinds,
                categories=tuple(
                    sorted({str(f.get("category") or "") for f in truth.get("fault") or []})
                ),
                services=services,
                alert_services=tuple(sorted(alert_services)),
            )
        )
    return sorted(out, key=lambda s: int(s.id.rsplit("-", 1)[1]))


def _iso(value: str) -> datetime | None:
    text = value.strip().replace("Z", "+00:00")
    if not text:
        return None
    # Nanoseconds do not parse; microseconds are plenty.
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)


def alerts(scenario: Scenario) -> list[AlertSignal]:
    """The alerts in alerting state when the incident was raised, as Alertmanager sends them."""
    path = next(iter(sorted(scenario.directory.rglob("alerts_in_alerting_state_*.json"))), None)
    if path is None:
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("data", {}).get("alerts", []) if isinstance(raw, Mapping) else raw
    signals: list[AlertSignal] = []
    for item in items or []:
        labels = {str(k): str(v) for k, v in (item.get("labels") or {}).items()}
        name = labels.get("alertname") or "alert"
        fingerprint = hashlib.sha256(json.dumps(labels, sort_keys=True).encode()).hexdigest()[:32]
        signals.append(
            AlertSignal(
                source="alertmanager",
                name=name[:200],
                fingerprint=fingerprint,
                status="firing" if item.get("state") == "firing" else "resolved",
                labels=labels,
                annotations={str(k): str(v) for k, v in (item.get("annotations") or {}).items()},
                starts_at=_iso(str(item.get("activeAt") or "")),
            )
        )
    return signals


def _event_line(body: str) -> tuple[datetime, str] | None:
    """One Kubernetes event as a log line: time, level, workload, reason and message."""
    try:
        wrapper = json.loads(body)
    except json.JSONDecodeError:
        return None
    event = wrapper.get("object") if isinstance(wrapper, Mapping) else None
    if not isinstance(event, Mapping) or event.get("apiVersion") != "v1":
        return None  # each event also appears as events.k8s.io/v1; the core copy is enough
    involved = event.get("involvedObject") or {}
    when = _iso(str(event.get("lastTimestamp") or event.get("eventTime") or ""))
    if when is None:
        return None
    level = "WARN" if event.get("type") == "Warning" else "INFO"
    who = workload(str(involved.get("name") or "kubernetes")) or "kubernetes"
    kind = str(involved.get("kind") or "Object")
    reason = str(event.get("reason") or "")
    message = " ".join(str(event.get("message") or "").split())
    stamp = when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return when, f"{stamp} {level} {who}: {kind} {involved.get('name', '')} {reason}: {message}"


def _rows(path: Path) -> Iterator[list[str]]:
    csv.field_size_limit(MAX_FIELD)
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader, None)  # the header
        yield from reader


def event_lines(scenario: Scenario, since: datetime, until: datetime) -> list[tuple[datetime, str]]:
    path = scenario.directory / "k8s_events_raw.tsv"
    if not path.is_file():
        return []
    out: list[tuple[datetime, str]] = []
    seen: set[str] = set()
    for row in _rows(path):
        if len(row) < 9:
            continue
        found = _event_line(row[8])
        if found is None or not since <= found[0] <= until or found[1] in seen:
            continue
        seen.add(found[1])  # an event updated in place is logged again unchanged
        out.append(found)
    return out


def log_lines(scenario: Scenario) -> list[tuple[datetime, str]]:
    """The kept window of the services' logs, as lines ARIA reads."""
    path = scenario.directory / WINDOW_FILE
    if not path.is_file():
        return []
    out: list[tuple[datetime, str]] = []
    for row in _rows(path):
        if len(row) != len(WINDOW_COLUMNS):
            continue
        ts, service, _pod, severity, body = row
        when = _iso(ts)
        if when is None:
            continue
        text = " ".join(body.split())
        canonical = normalize_level(_OTEL_LEVELS.get(severity.strip().lower(), severity))
        level = f"{canonical} " if canonical else ""
        stamp = when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        out.append((when, f"{stamp} {level}{service or 'app'}: {text}"))
    return out


def window(scenario: Scenario, minutes: int) -> tuple[datetime, datetime] | None:
    if scenario.raised_at is None:
        return None
    return scenario.raised_at - timedelta(minutes=minutes), scenario.raised_at


def scenario_lines(scenario: Scenario, minutes: int) -> list[str]:
    """Kubernetes events and service logs from the minutes before the incident, in time order."""
    span = window(scenario, minutes)
    if span is None:
        return []
    merged = event_lines(scenario, *span) + log_lines(scenario)
    merged.sort(key=lambda item: item[0])
    return [line for _, line in merged]


# --- the download's stream reader -------------------------------------------------------------


class _HashingReader(io.RawIOBase):
    """Bytes from an HTTP response, hashed as they are read."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        super().__init__()
        self._chunks = chunks
        self._pending = b""
        self.sha256 = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:  # type: ignore[override]
        while not self._pending:
            chunk = next(self._chunks, None)
            if chunk is None:
                return 0
            self.sha256.update(chunk)
            self._pending = chunk
        n = min(len(buffer), len(self._pending))
        buffer[:n] = self._pending[:n]
        self._pending = self._pending[n:]
        return n


def keep_window(
    rows: Iterator[list[str]], since: datetime, until: datetime, limit: int | None = None
) -> list[tuple[str, str, str, str, str]]:
    """The newest ``limit`` log rows (all by default) between ``since`` and ``until``, oldest
    first: time, service, pod, severity and body."""
    kept: list[tuple[datetime, tuple[str, str, str, str, str]]] = []
    for row in rows:
        if len(row) < 11:
            continue
        when = _iso(row[0])
        if when is None or not since <= when <= until:
            continue
        pod = _POD.search(row[10])
        kept.append((when, (row[0], row[7], pod.group(1) if pod else "", row[5], row[8])))
    kept.sort(key=lambda item: item[0])
    chosen = kept if limit is None else kept[-limit:]
    return [values for _, values in chosen]


def _write_window(path: Path, rows: Sequence[Sequence[str]]) -> None:
    partial = path.with_name(path.name + ".part")
    with (
        partial.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as packed,
        io.TextIOWrapper(packed, encoding="utf-8", newline="") as handle,
    ):
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(WINDOW_COLUMNS)
        writer.writerows(rows)
    partial.replace(path)


def write_log_windows(
    source: DataSource, dest: Path, client: httpx.Client, _url: str | None
) -> list[Path]:
    """Stream reader for ``aria data download``: each scenario's log window, from its full log
    checked against the Hub's sha256 as it streams in."""
    from aria.data.download import (  # noqa: PLC0415 - import cycle
        DownloadError,
        hub_files,
        hub_repo,
        hub_url,
    )

    stream = source.stream
    if stream is None or not stream.minutes or not stream.limit or not source.commit:
        msg = f"{source.name}: the ITBench reader needs minutes, limit and a pinned commit"
        raise DownloadError(msg)
    repo = hub_repo(source.url or "")
    logs = {
        entry["path"]: entry
        for entry in hub_files(
            client, repo, source.commit, ["snapshots/sre/*/Scenario-*/otel_logs_raw.tsv"]
        )
    }
    written: list[Path] = []
    for scenario in find_scenarios(dest):
        target = scenario.directory / WINDOW_FILE
        written.append(target)
        span = window(scenario, stream.minutes)
        relative = (scenario.directory / "otel_logs_raw.tsv").relative_to(dest).as_posix()
        entry = logs.get(relative)
        if target.exists() or span is None or entry is None:
            if not target.exists():
                _write_window(target, [])  # no incident time or no log: an empty window
            continue
        for attempt in range(3):
            try:
                rows, digest = _read_window(client, hub_url(repo, source.commit, relative), span)
                break
            except httpx.TransportError:  # a transfer cut off part way: read it again
                if attempt == 2:
                    raise
        else:  # pragma: no cover - the loop either breaks or raises
            continue
        expected = (entry.get("lfs") or {}).get("oid")
        if expected and digest != expected:
            msg = f"{relative}: sha256 mismatch (the Hub records {expected})"
            raise DownloadError(msg)
        _write_window(target, rows[-stream.limit :])
    return written


def _read_window(
    client: httpx.Client, url: str, span: tuple[datetime, datetime]
) -> tuple[list[tuple[str, str, str, str, str]], str]:
    """(rows of the window, sha256 of the whole file) from one streamed read of a log."""
    from aria.data.download import DownloadError  # noqa: PLC0415 - import cycle

    with client.stream("GET", url) as response:
        if response.status_code != httpx.codes.OK:
            msg = f"GET {url} returned {response.status_code}"
            raise DownloadError(msg)
        raw = _HashingReader(response.iter_bytes(1 << 20))
        text = io.TextIOWrapper(
            io.BufferedReader(raw), encoding="utf-8", errors="replace", newline=""
        )
        csv.field_size_limit(MAX_FIELD)
        reader = csv.reader(text, delimiter="\t")
        next(reader, None)
        rows = keep_window(reader, *span, limit=None)
        for _ in iter(lambda: raw.read(1 << 20), b""):
            pass  # hash any bytes the parser did not need to read
    return rows, raw.sha256.hexdigest()
