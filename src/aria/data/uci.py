"""The UCI "Incident management process enriched event log" (ServiceNow audit trail).

Each row is one state change of one incident. ARIA aggregates rows per incident into:

* fields known when the ticket was opened (category, subcategory, symptom, CI, channel,
  location, first assignment group) - the inputs a priority model may use;
* outcomes known only later (final priority, SLA met, reopen and reassignment counts,
  resolution time) - the labels and the "repeat history" statistics.

Values are anonymised codes such as ``Category 55``; missing values are ``?``. There is no free
text, so the dataset supplies priority and SLA history, not fix descriptions.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

UCI_COLUMNS = (
    "number", "incident_state", "active", "reassignment_count", "reopen_count", "sys_mod_count",
    "made_sla", "caller_id", "opened_by", "opened_at", "sys_created_by", "sys_created_at",
    "sys_updated_by", "sys_updated_at", "contact_type", "location", "category", "subcategory",
    "u_symptom", "cmdb_ci", "impact", "urgency", "priority", "assignment_group", "assigned_to",
    "knowledge", "u_priority_confirmation", "notify", "problem_id", "rfc", "vendor", "caused_by",
    "closed_code", "resolved_by", "resolved_at", "closed_at",
)  # fmt: skip
_DATE_COLUMNS = ("opened_at", "sys_created_at", "sys_updated_at", "resolved_at", "closed_at")
_INT_COLUMNS = ("reassignment_count", "reopen_count", "sys_mod_count")
_BOOL_COLUMNS = ("active", "made_sla", "knowledge", "u_priority_confirmation")
PRIORITIES = ("1 - Critical", "2 - High", "3 - Moderate", "4 - Low")


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return None if value in ("", "?") else value


def _date(value: str | None) -> datetime | None:
    value = _clean(value)
    if value is None:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _bool(value: str | None) -> bool | None:
    value = _clean(value)
    if value is None:
        return None
    return value.lower() in ("true", "1", "yes")


def _int(value: str | None) -> int | None:
    value = _clean(value)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def parse_event(row: dict[str, str]) -> dict[str, Any]:
    """Type one CSV row. Unknown columns are rejected so schema drift fails loudly."""
    unknown = set(row) - set(UCI_COLUMNS)
    if unknown:
        msg = f"unexpected UCI columns: {sorted(unknown)}"
        raise ValueError(msg)
    event: dict[str, Any] = {}
    for column in UCI_COLUMNS:
        raw = row.get(column)
        if column in _DATE_COLUMNS:
            event[column] = _date(raw)
        elif column in _INT_COLUMNS:
            event[column] = _int(raw)
        elif column in _BOOL_COLUMNS:
            event[column] = _bool(raw)
        else:
            event[column] = _clean(raw)
    return event


def iter_events(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        for row in csv.DictReader(handle):
            yield parse_event(row)


def find_event_log(raw_dir: Path) -> Path | None:
    for candidate in sorted(raw_dir.rglob("*.csv")):
        if "incident" in candidate.name.lower():
            return candidate
    return None


@dataclass(slots=True)
class IncidentSummary:
    number: str
    opened_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    category: str | None
    subcategory: str | None
    symptom: str | None
    cmdb_ci: str | None
    contact_type: str | None
    location: str | None
    first_assignment_group: str | None
    final_assignment_group: str | None
    impact: str | None
    urgency: str | None
    priority_at_open: str | None
    priority: str | None
    knowledge: bool | None
    priority_confirmation: bool | None
    made_sla: bool | None
    reopen_count: int
    reassignment_count: int
    sys_mod_count: int
    closed_code: str | None
    resolution_hours: float | None
    n_events: int
    split: str = "train"


def _order_key(event: dict[str, Any]) -> tuple[int, datetime]:
    return (event.get("sys_mod_count") or 0, event.get("sys_updated_at") or datetime.min.replace(tzinfo=UTC))


def aggregate(events: Iterable[dict[str, Any]]) -> list[IncidentSummary]:
    by_number: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("number"):
            by_number[event["number"]].append(event)
    summaries: list[IncidentSummary] = []
    for number, rows in by_number.items():
        rows.sort(key=_order_key)
        first, last = rows[0], rows[-1]
        opened = first.get("opened_at")
        resolved = next((r["resolved_at"] for r in reversed(rows) if r.get("resolved_at")), None)
        hours = (resolved - opened).total_seconds() / 3600 if opened and resolved else None
        summaries.append(
            IncidentSummary(
                number=number,
                opened_at=opened,
                resolved_at=resolved,
                closed_at=last.get("closed_at"),
                category=first.get("category"),
                subcategory=first.get("subcategory"),
                symptom=first.get("u_symptom"),
                cmdb_ci=first.get("cmdb_ci"),
                contact_type=first.get("contact_type"),
                location=first.get("location"),
                first_assignment_group=first.get("assignment_group"),
                final_assignment_group=last.get("assignment_group"),
                impact=first.get("impact"),
                urgency=first.get("urgency"),
                priority_at_open=first.get("priority"),
                priority=last.get("priority"),
                knowledge=first.get("knowledge"),
                priority_confirmation=first.get("u_priority_confirmation"),
                made_sla=last.get("made_sla"),
                reopen_count=max((r.get("reopen_count") or 0) for r in rows),
                reassignment_count=max((r.get("reassignment_count") or 0) for r in rows),
                sys_mod_count=max((r.get("sys_mod_count") or 0) for r in rows),
                closed_code=last.get("closed_code"),
                resolution_hours=hours if hours is None or hours >= 0 else None,
                n_events=len(rows),
            )
        )
    assign_time_splits(summaries)
    return summaries


def assign_time_splits(
    summaries: list[IncidentSummary], train: float = 0.70, calib: float = 0.15
) -> None:
    """Split by open time so models never train on the future (no temporal leakage)."""
    ordered = sorted(
        summaries, key=lambda s: (s.opened_at or datetime.min.replace(tzinfo=UTC), s.number)
    )
    n = len(ordered)
    for i, summary in enumerate(ordered):
        fraction = i / n if n else 0
        summary.split = "train" if fraction < train else "calib" if fraction < train + calib else "test"
