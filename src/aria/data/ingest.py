"""Load downloaded datasets into the database.

Each loader is idempotent: it deletes the rows of its own dataset before inserting, so
re-running ``aria data ingest`` after a manifest change never duplicates data.
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, delete, insert

from aria.data.labels import label_window, load_rubric, tag_stats
from aria.data.loghub import LOGHUB_DIRS, LogRecord, iter_raw_log, iter_structured_csv
from aria.data.uci import IncidentSummary, aggregate, find_event_log, iter_events
from aria.db.engine import session_scope
from aria.db.models import (
    ItsmEventRow,
    ItsmIncidentRow,
    LogEventRow,
    LogWindowRow,
)
from aria.observability.logging import get_logger

log = get_logger(__name__)
BATCH = 5_000
_BLOCK = re.compile(r"blk_-?\d+")


@dataclass
class IngestResult:
    dataset: str
    events: int = 0
    windows: int = 0
    incidents: int = 0


def _batched(rows: Iterable[dict[str, Any]], size: int = BATCH) -> Iterator[list[dict[str, Any]]]:
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(row)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _event_row(dataset: str, rec: LogRecord, window_id: str | None = None) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "system": rec.system,
        "line_no": rec.line_no,
        "ts": rec.ts,
        "node": (rec.node or None) and rec.node[:160],
        "component": (rec.component or None) and rec.component[:160],
        "level": rec.level,
        "message": rec.message,
        "label": rec.label,
        "gt_template": rec.gt_template,
        "window_id": window_id,
    }


def _replace_dataset(engine: Engine, dataset: str) -> None:
    with session_scope(engine) as session:
        session.execute(delete(LogEventRow).where(LogEventRow.dataset == dataset))
        session.execute(delete(LogWindowRow).where(LogWindowRow.dataset == dataset))


def _insert_events(engine: Engine, rows: Iterable[dict[str, Any]]) -> int:
    count = 0
    for batch in _batched(rows):
        with session_scope(engine) as session:
            session.execute(insert(LogEventRow), batch)
        count += len(batch)
    return count


def ingest_loghub_samples(engine: Engine, loghub_dir: Path, dataset: str = "loghub-2k") -> IngestResult:
    """The 16 official 2k-line samples, with ground-truth templates and BGL alert tags."""
    _replace_dataset(engine, dataset)
    result = IngestResult(dataset)
    for directory, system in LOGHUB_DIRS.items():
        path = loghub_dir / directory / f"{directory}_2k.log_structured.csv"
        if path.exists():
            result.events += _insert_events(
                engine, (_event_row(dataset, rec) for rec in iter_structured_csv(system, path))
            )
    log.info("ingest.done", dataset=dataset, events=result.events)
    return result


def ingest_hdfs_100k(engine: Engine, hdfs_dir: Path, dataset: str = "hdfs-100k") -> IngestResult:
    """Contiguous HDFS lines; a line is labelled `anomaly` when its block is labelled Anomaly."""
    structured = next(hdfs_dir.rglob("HDFS_100k.log_structured.csv"), None)
    labels_path = next(hdfs_dir.rglob("anomaly_label.csv"), None)
    if structured is None or labels_path is None:
        return IngestResult(dataset)
    anomalous: set[str] = set()
    with labels_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("Label") == "Anomaly":
                anomalous.add(row["BlockId"])
    _replace_dataset(engine, dataset)

    def rows() -> Iterator[dict[str, Any]]:
        for rec in iter_structured_csv("hdfs", structured):
            blocks = set(_BLOCK.findall(rec.message))
            rec.label = "anomaly" if blocks & anomalous else None
            yield _event_row(dataset, rec)

    result = IngestResult(dataset, events=_insert_events(engine, rows()))
    log.info("ingest.done", dataset=dataset, events=result.events)
    return result


def _window_start(ts: datetime, minutes: int) -> datetime:
    floored = ts.replace(second=0, microsecond=0)
    return floored - timedelta(minutes=floored.minute % minutes)


def build_bgl_windows(
    records: list[LogRecord], *, window_min: int = 10, min_events: int = 5
) -> tuple[list[dict[str, Any]], dict[int, str]]:
    """Tumbling time windows labelled by the BGL alert-tag rubric; time-ordered splits."""
    rubric = load_rubric()
    buckets: dict[datetime, list[int]] = defaultdict(list)
    for i, rec in enumerate(records):
        if rec.ts is not None:
            buckets[_window_start(rec.ts, window_min)].append(i)
    starts = sorted(start for start, idx in buckets.items() if len(idx) >= min_events)
    windows: list[dict[str, Any]] = []
    assignment: dict[int, str] = {}
    for n, start in enumerate(starts):
        idx = buckets[start]
        window_id = f"bgl-{start:%Y%m%dT%H%M}"
        stats = tag_stats(
            ((records[i].label or "", records[i].node) for i in idx if records[i].label), rubric
        )
        severity, detail = label_window(stats, rubric)
        fraction = n / len(starts)
        windows.append(
            {
                "id": window_id,
                "dataset": "loghub-bgl",
                "system": "bgl",
                "start_ts": start,
                "end_ts": start + timedelta(minutes=window_min),
                "n_events": len(idx),
                "alert_tags": dict(stats.tags),
                "label_severity": severity.value,
                "label_source": "bgl_alert_tags",
                "label_detail": detail,
                "split": "train" if fraction < 0.6 else "calib" if fraction < 0.8 else "test",
                "synthetic": False,
            }
        )
        for i in idx:
            assignment[i] = window_id
    return windows, assignment


def ingest_bgl_full(
    engine: Engine, bgl_dir: Path, *, max_lines: int = 500_000, dataset: str = "loghub-bgl"
) -> IngestResult:
    log_path = next((p for p in bgl_dir.rglob("BGL.log") if p.is_file()), None)
    if log_path is None:
        return IngestResult(dataset)
    records = list(iter_raw_log("bgl", log_path, limit=max_lines))
    windows, assignment = build_bgl_windows(records)
    _replace_dataset(engine, dataset)
    with session_scope(engine) as session:
        for batch in _batched(windows):
            session.execute(insert(LogWindowRow), batch)
    events = _insert_events(
        engine, (_event_row(dataset, rec, assignment.get(i)) for i, rec in enumerate(records))
    )
    log.info("ingest.done", dataset=dataset, events=events, windows=len(windows))
    return IngestResult(dataset, events=events, windows=len(windows))


def _incident_row(summary: IncidentSummary) -> dict[str, Any]:
    return {
        "number": summary.number,
        "opened_at": summary.opened_at,
        "resolved_at": summary.resolved_at,
        "closed_at": summary.closed_at,
        "category": summary.category,
        "subcategory": summary.subcategory,
        "symptom": summary.symptom,
        "cmdb_ci": summary.cmdb_ci,
        "contact_type": summary.contact_type,
        "location": summary.location,
        "first_assignment_group": summary.first_assignment_group,
        "final_assignment_group": summary.final_assignment_group,
        "impact": summary.impact,
        "urgency": summary.urgency,
        "priority_at_open": summary.priority_at_open,
        "priority": summary.priority,
        "knowledge": summary.knowledge,
        "priority_confirmation": summary.priority_confirmation,
        "made_sla": summary.made_sla,
        "reopen_count": summary.reopen_count,
        "reassignment_count": summary.reassignment_count,
        "sys_mod_count": summary.sys_mod_count,
        "closed_code": summary.closed_code,
        "resolution_hours": summary.resolution_hours,
        "n_events": summary.n_events,
        "split": summary.split,
    }


def ingest_uci(engine: Engine, uci_dir: Path) -> IngestResult:
    path = find_event_log(uci_dir)
    if path is None:
        return IngestResult("uci-incidents")
    events = list(iter_events(path))
    summaries = aggregate(events)
    with session_scope(engine) as session:
        session.execute(delete(ItsmEventRow))
        session.execute(delete(ItsmIncidentRow))
    for batch in _batched(events):
        with session_scope(engine) as session:
            session.execute(insert(ItsmEventRow), batch)
    for batch in _batched(_incident_row(s) for s in summaries):
        with session_scope(engine) as session:
            session.execute(insert(ItsmIncidentRow), batch)
    log.info("ingest.done", dataset="uci-incidents", events=len(events), incidents=len(summaries))
    return IngestResult("uci-incidents", events=len(events), incidents=len(summaries))


def ingest_all(engine: Engine, raw_dir: Path, *, bgl_max_lines: int = 500_000) -> list[IngestResult]:
    """Ingest every source that has been downloaded; missing sources are skipped."""
    results: list[IngestResult] = []
    if (raw_dir / "loghub-2k").exists():
        results.append(ingest_loghub_samples(engine, raw_dir / "loghub-2k"))
    if (raw_dir / "hdfs-100k").exists():
        results.append(ingest_hdfs_100k(engine, raw_dir / "hdfs-100k"))
    if (raw_dir / "loghub-bgl").exists():
        results.append(ingest_bgl_full(engine, raw_dir / "loghub-bgl", max_lines=bgl_max_lines))
    if (raw_dir / "uci-incidents").exists():
        results.append(ingest_uci(engine, raw_dir / "uci-incidents"))
    return results
