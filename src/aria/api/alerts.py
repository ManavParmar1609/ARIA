"""Alert webhooks: Alertmanager and Grafana payloads become grouped triage runs.

Alerts that share a group key (Alertmanager's ``groupKey``, else the common labels) and arrive
within ``triggers.alert_group_window_s`` of the group's last alert join the open group instead
of starting a new run, so an alert storm becomes one incident. That holds across API replicas
too: the database keeps one open group per key (a unique index), and a group's run takes an ID
that follows from the group, so requests that race to open either end up with the same one.
Names, labels and annotations are untrusted: secrets are redacted before they are stored, and
when a run starts its addresses are pseudonymised and any value that reads like an instruction is
withheld (``security.fields``).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from aria.contracts.base import utcnow
from aria.contracts.inputs import AlertSignal, RunOptions, TriageRequest
from aria.contracts.run import RunStatus
from aria.db.engine import session_scope
from aria.db.models import AlertGroupRow, AlertRow, RunRow
from aria.security.fields import clean_map, strip_secrets

SYSTEM_LABELS = ("aria_system", "system", "job", "service")
# What one webhook payload can store: Alertmanager groups rarely carry more than a few dozen.
MAX_ALERTS_PER_PAYLOAD = 500
MAX_LABELS = 64
_KNOWN_SYSTEMS = frozenset(
    {
        "bgl", "thunderbird", "hdfs", "hadoop", "spark", "zookeeper", "openstack", "hpc",
        "windows", "linux", "mac", "android", "healthapp", "apache", "openssh", "proxifier",
    }
)  # fmt: skip


def _ts(value: Any) -> datetime | None:
    if not value or str(value).startswith("0001-01-01"):
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _fingerprint(labels: dict[str, str]) -> str:
    blob = json.dumps(labels, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def _clean_map(values: Any, limit: int) -> dict[str, str]:
    """Labels or annotations as short strings, with secrets redacted before anything stores them."""
    if not isinstance(values, dict):
        return {}
    bounded = {str(k)[:64]: str(v)[:limit] for k, v in list(values.items())[:MAX_LABELS]}
    return clean_map(bounded, strip_secrets)


def normalize(
    payload: dict[str, Any], *, source: str
) -> tuple[str, list[AlertSignal], dict[str, str]]:
    """Group key, alerts and common labels from an Alertmanager-format webhook payload."""
    common = _clean_map(payload.get("commonLabels"), 256)
    alerts: list[AlertSignal] = []
    listed = payload.get("alerts")
    # A payload of another shape (a string, a map, a list of non-objects) has no alerts: 422, so
    # the sender does not retry it as it would a 500.
    for raw in (listed if isinstance(listed, list) else [])[:MAX_ALERTS_PER_PAYLOAD]:
        if not isinstance(raw, dict):
            continue
        given = raw.get("labels")
        raw_labels = {
            str(k)[:64]: str(v)[:256]
            for k, v in list((given if isinstance(given, dict) else {}).items())[:MAX_LABELS]
        }
        labels = _clean_map(raw_labels, 256)
        annotations = _clean_map(raw.get("annotations"), 1_000)
        name = strip_secrets(str(labels.get("alertname") or payload.get("title") or ""))[:200]
        alerts.append(
            AlertSignal(
                source=source,  # type: ignore[arg-type]
                name=name.strip() or "alert",
                fingerprint=str(raw.get("fingerprint") or _fingerprint(raw_labels))[:128],
                status="resolved" if raw.get("status") == "resolved" else "firing",
                labels=labels,
                annotations=annotations,
                starts_at=_ts(raw.get("startsAt")),
                ends_at=_ts(raw.get("endsAt")),
            )
        )
    key = str(payload.get("groupKey") or "")
    if not key:
        # Without a group key, alerts group by the labels they share; alerts that share none group
        # only with the same alerts again, so unrelated ones never merge into one run.
        shared = common or {a.fingerprint: a.name for a in alerts}
        key = f"{source}:{'labels' if common else 'alerts'}:{_fingerprint(shared)}"
    return key[:256], alerts, common


def system_for(common: dict[str, str], alerts: list[AlertSignal]) -> str:
    for label in SYSTEM_LABELS:
        for candidate in [common.get(label), *(a.labels.get(label) for a in alerts)]:
            if candidate and candidate.lower() in _KNOWN_SYSTEMS:
                return candidate.lower()
    return "generic"


def title_for(alerts: list[AlertSignal], common: dict[str, str]) -> str:
    names = sorted({a.name for a in alerts})
    head = names[0] if names else "Alert"
    more = f" and {len(names) - 1} more" if len(names) > 1 else ""
    where = common.get("service") or common.get("job") or common.get("instance")
    return f"{head}{more}" + (f" on {where}" if where else "")


class Grouping(NamedTuple):
    """Where a payload's alerts went."""

    group_id: str
    run_id: str | None  # the group's run, once one is attached
    grouped: bool  # joined an open group, rather than opening one
    first_at: datetime  # when the group opened: its run's IDs follow from it


def new_group_id() -> str:
    return f"grp-{uuid.uuid4().hex[:12]}"


def run_ids_for(group: Grouping) -> list[str]:
    """The IDs the group's run may take, in order. Requests that race to open the run try them
    in the same order and stop at the same one: the first that is free, or already the group's.
    Past the first, they matter only if some other run already holds the first."""
    stem = f"run-{group.first_at:%Y%m%d}-"
    seeds = [group.group_id.removeprefix("grp-")] + [
        hashlib.sha256(f"{group.group_id}:{n}".encode()).hexdigest() for n in (1, 2, 3)
    ]
    return [stem + seed[:10] for seed in seeds]


def opened_by(run: dict[str, Any], group_id: str) -> bool:
    """Whether ``run`` is the group's own run, not another run with the same ID."""
    return run.get("alert_group_id") == group_id


def record_alerts(
    engine: Any,
    key: str,
    alerts: list[AlertSignal],
    *,
    system: str,
    window_s: int,
) -> Grouping:
    """Store the alerts and find or open their group."""
    try:
        return _record(engine, key, alerts, system=system, window_s=window_s)
    except IntegrityError:  # another request opened this key's group a moment ago: join it
        return _record(engine, key, alerts, system=system, window_s=window_s)


def _record(
    engine: Any, key: str, alerts: list[AlertSignal], *, system: str, window_s: int
) -> Grouping:
    now = utcnow()
    with session_scope(engine) as session:
        group = session.scalar(
            select(AlertGroupRow)
            .where(AlertGroupRow.key == key, AlertGroupRow.status == "open")
            .order_by(AlertGroupRow.last_at.desc())
        )
        if group is not None:
            last = group.last_at if group.last_at.tzinfo else group.last_at.replace(tzinfo=UTC)
            run = session.get(RunRow, group.run_id) if group.run_id else None
            gone = group.run_id is not None and run is None  # its run was deleted
            if (
                gone
                or now - last > timedelta(seconds=window_s)
                or (run is not None and RunStatus(run.status).terminal)
            ):
                group.status = "closed"
                session.flush()  # closed before the new group opens: one open group per key
                group = None
        grouped = group is not None
        if group is None:
            group = AlertGroupRow(
                id=new_group_id(),
                key=key,
                system=system,
                status="open",
                alert_count=0,  # column defaults apply on insert, not on the new object
                first_at=now,
                last_at=now,
            )
            session.add(group)
        group.alert_count += len(alerts)
        group.last_at = now
        for alert in alerts:
            session.add(
                AlertRow(
                    fingerprint=alert.fingerprint,
                    source=alert.source,
                    name=alert.name,
                    status=alert.status,
                    labels=alert.labels,
                    annotations=alert.annotations,
                    starts_at=alert.starts_at,
                    ends_at=alert.ends_at,
                    received_at=now,
                    group_id=group.id,
                )
            )
        return Grouping(group.id, group.run_id, grouped, group.first_at)


def attach_run(engine: Any, group_id: str, run_id: str) -> str:
    """Make ``run_id`` the group's run unless it has one already; returns the group's run."""
    with session_scope(engine) as session:
        session.execute(
            update(AlertGroupRow)
            .where(AlertGroupRow.id == group_id, AlertGroupRow.run_id.is_(None))
            .values(run_id=run_id)
        )
        attached = session.scalar(select(AlertGroupRow.run_id).where(AlertGroupRow.id == group_id))
    return attached or run_id


def triage_request(alerts: list[AlertSignal], common: dict[str, str], system: str) -> TriageRequest:
    return TriageRequest(
        title=title_for(alerts, common)[:200],
        system=system,
        service=(common.get("service") or "")[:120] or None,
        environment=(common.get("env") or common.get("environment") or "")[:64] or None,
        alerts=alerts[:50],
        options=RunOptions(),
    )
