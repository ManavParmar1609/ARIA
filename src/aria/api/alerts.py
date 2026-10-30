"""Alert webhooks: Alertmanager and Grafana payloads become grouped triage runs.

Alerts that share a group key (Alertmanager's ``groupKey``, else the common labels) and arrive
within ``triggers.alert_group_window_s`` of the group's last alert join the open group instead
of starting a new run, so an alert storm becomes one incident. That holds across API replicas
too: a new group's ID follows from its key and the group before it, and its run's ID from the
group, so requests that race to open either compute the same ID and the database keeps one.
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

from sqlalchemy import select
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
    opens: str  # the run the group opens while it has none


def group_id_after(key: str, previous: str | None) -> str:
    """The ID of the group that follows ``previous`` for ``key`` (None: the key's first group).
    Requests that race to open it, on two API replicas or one retrying, compute the same ID."""
    digest = hashlib.sha256(f"{key}\x1f{previous or ''}".encode()).hexdigest()
    return f"grp-{digest[:20]}"


def run_id_for(group_id: str, first_at: datetime) -> str:
    """The run an alert group opens: every request that joins the group before its run is
    attached names this one, and a run created twice is kept once."""
    return f"run-{first_at:%Y%m%d}-{group_id.removeprefix('grp-')[:10]}"


def opened_by(run: dict[str, Any], group_id: str) -> bool:
    """Whether ``run`` is the live run ``group_id`` opened, not an older one with the same ID."""
    return run.get("alert_group_id") == group_id and not RunStatus(run["status"]).terminal


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
        return _record(engine, key, alerts, system=system, window_s=window_s, follow=True)
    except IntegrityError:  # another request opened this group a moment ago: join it
        return _record(engine, key, alerts, system=system, window_s=window_s, follow=False)


def _record(
    engine: Any,
    key: str,
    alerts: list[AlertSignal],
    *,
    system: str,
    window_s: int,
    follow: bool,
) -> Grouping:
    now = utcnow()
    with session_scope(engine) as session:
        group = session.scalar(
            select(AlertGroupRow)
            .where(AlertGroupRow.key == key, AlertGroupRow.status == "open")
            .order_by(AlertGroupRow.last_at.desc())
        )
        previous = group.id if group is not None else None
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
                group = None
        if previous is None:
            previous = session.scalar(
                select(AlertGroupRow.id)
                .where(AlertGroupRow.key == key)
                .order_by(AlertGroupRow.first_at.desc(), AlertGroupRow.id.desc())
                .limit(1)
            )
        grouped = group is not None
        if group is None:
            group = AlertGroupRow(
                # The next group in the key's chain; after a lost race, one of its own.
                id=group_id_after(key, previous) if follow else f"grp-{uuid.uuid4().hex[:20]}",
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
        return Grouping(group.id, group.run_id, grouped, run_id_for(group.id, group.first_at))


def attach_run(engine: Any, group_id: str, run_id: str) -> None:
    with session_scope(engine) as session:
        group = session.get(AlertGroupRow, group_id)
        if group is not None:
            group.run_id = run_id


def triage_request(alerts: list[AlertSignal], common: dict[str, str], system: str) -> TriageRequest:
    return TriageRequest(
        title=title_for(alerts, common)[:200],
        system=system,
        service=(common.get("service") or "")[:120] or None,
        environment=(common.get("env") or common.get("environment") or "")[:64] or None,
        alerts=alerts[:50],
        options=RunOptions(),
    )
