"""Alert webhooks: Alertmanager and Grafana payloads become grouped triage runs.

Alerts that share a group key (Alertmanager's ``groupKey``, else the common labels) and arrive
within ``triggers.alert_group_window_s`` of the group's last alert join the open group instead
of starting a new run, so an alert storm becomes one incident. Label and annotation values are
untrusted: they reach models only as fenced evidence, and instruction-like ones are withheld.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from aria.contracts.base import utcnow
from aria.contracts.inputs import AlertSignal, RunOptions, TriageRequest
from aria.contracts.run import RunStatus
from aria.db.engine import session_scope
from aria.db.models import AlertGroupRow, AlertRow, RunRow

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


def normalize(
    payload: dict[str, Any], *, source: str
) -> tuple[str, list[AlertSignal], dict[str, str]]:
    """Group key, alerts and common labels from an Alertmanager-format webhook payload."""
    common = {
        str(k)[:64]: str(v)[:256]
        for k, v in list((payload.get("commonLabels") or {}).items())[:MAX_LABELS]
    }
    alerts: list[AlertSignal] = []
    for raw in (payload.get("alerts") or [])[:MAX_ALERTS_PER_PAYLOAD]:
        labels = {
            str(k)[:64]: str(v)[:256]
            for k, v in list((raw.get("labels") or {}).items())[:MAX_LABELS]
        }
        annotations = {
            str(k)[:64]: str(v)[:1_000]
            for k, v in list((raw.get("annotations") or {}).items())[:MAX_LABELS]
        }
        name = labels.get("alertname") or payload.get("title") or "alert"
        alerts.append(
            AlertSignal(
                source=source,  # type: ignore[arg-type]
                name=str(name)[:200],
                fingerprint=str(raw.get("fingerprint") or _fingerprint(labels))[:128],
                status="resolved" if raw.get("status") == "resolved" else "firing",
                labels=labels,
                annotations=annotations,
                starts_at=_ts(raw.get("startsAt")),
                ends_at=_ts(raw.get("endsAt")),
            )
        )
    key = str(payload.get("groupKey") or "") or f"labels:{_fingerprint(common)}"
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


def record_alerts(
    engine: Any,
    key: str,
    alerts: list[AlertSignal],
    *,
    system: str,
    window_s: int,
) -> tuple[str, str | None, bool]:
    """Store the alerts and find or open their group. Returns (group id, run id, grouped)."""
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
            if now - last > timedelta(seconds=window_s) or (
                run is not None and RunStatus(run.status).terminal
            ):
                group.status = "closed"
                group = None
        grouped = group is not None
        if group is None:
            group = AlertGroupRow(
                id=f"grp-{uuid.uuid4().hex[:12]}",
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
        return group.id, group.run_id, grouped


def attach_run(engine: Any, group_id: str, run_id: str) -> None:
    with session_scope(engine) as session:
        group = session.get(AlertGroupRow, group_id)
        if group is not None:
            group.run_id = run_id


def triage_request(alerts: list[AlertSignal], common: dict[str, str], system: str) -> TriageRequest:
    return TriageRequest(
        title=title_for(alerts, common)[:200],
        system=system,
        service=common.get("service"),
        environment=common.get("env") or common.get("environment"),
        alerts=alerts[:50],
        options=RunOptions(),
    )
