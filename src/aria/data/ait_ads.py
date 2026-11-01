"""The AIT Alert Data Set (Landauer, Skopik and Wurzenberger, CSET 2024).

Eight small company networks (mail, file share, web server, VPN, firewall, intranet) were run
with simulated users for several days, and each was attacked once in several steps. Three
intrusion detection systems watched them: Wazuh (host logs), Suricata (network traffic, also
re-read by Wazuh from its fast log) and AMiner (log anomalies). ``labels.csv`` gives the start
and end of every attack step in each scenario.

Each alert becomes one line, as a SIEM forwards it: the time, the host or sensor that raised
it, and the alert's own text (the rule, its description and the log line it fired on). The
attack steps are the labels and never reach a line. The data stays in its zip (2.9 GB
unpacked) and is read in time order, scenario by scenario, as it streams out.
"""

from __future__ import annotations

import csv
import heapq
import io
import json
import zipfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

AIT_DIR = Path("data/raw/ait-ads")
ARCHIVE = "ait_ads.zip"
LABELS = "labels.csv"
AIT_CITATION = (
    "M. Landauer, F. Skopik, M. Wurzenberger. Introducing a New Alert Data Set for Multi-Step "
    "Attack Analysis. CSET 2024. Zenodo, DOI 10.5281/zenodo.8263181."
)
MAX_LINE = 2_000  # characters: the longest audit records run to several thousand


@dataclass(frozen=True)
class Phase:
    scenario: str
    name: str  # e.g. "webshell", "privilege_escalation"
    start: float  # seconds since the epoch, UTC
    end: float


@dataclass(frozen=True)
class Alert:
    ts: float  # seconds since the epoch, UTC
    source: str  # "wazuh", "suricata" or "aminer"
    level: int | None  # the detector's own severity: Wazuh's rule level (0-15) where it has one
    line: str  # what ARIA reads


def find(root: Path = AIT_DIR) -> Path | None:
    archive = root / ARCHIVE
    return archive if archive.is_file() and (root / LABELS).is_file() else None


def read_phases(root: Path = AIT_DIR) -> dict[str, list[Phase]]:
    """Scenario -> its attack steps, in time order."""
    phases: dict[str, list[Phase]] = {}
    with (root / LABELS).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            phase = Phase(
                scenario=row["scenario"].strip(),
                name=row["attack"].strip(),
                start=float(row["start"]),
                end=float(row["end"]),
            )
            phases.setdefault(phase.scenario, []).append(phase)
    return {k: sorted(v, key=lambda p: p.start) for k, v in sorted(phases.items())}


def scenarios(root: Path = AIT_DIR) -> list[str]:
    archive = find(root)
    if archive is None:
        return []
    with zipfile.ZipFile(archive) as bundle:
        names = {n.rsplit("_", 1)[0] for n in bundle.namelist() if n.endswith("_wazuh.json")}
    return sorted(names & set(read_phases(root)))


def _stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _clip(text: str) -> str:
    return " ".join(text.split())[:MAX_LINE]


def wazuh_alert(raw: Mapping[str, Any]) -> Alert | None:
    """One record of ``<scenario>_wazuh.json``: a Wazuh alert, or a Suricata one it relays."""
    stamp = str(raw.get("@timestamp") or "")
    try:
        ts = datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return None
    rule = raw.get("rule") or {}
    level = rule.get("level")
    alert = (raw.get("data") or {}).get("alert")
    if isinstance(alert, Mapping):  # Suricata's own event, relayed whole
        data = raw.get("data") or {}
        text = (
            f"{alert.get('category') or 'alert'}: {alert.get('signature') or ''} "
            f"{data.get('proto') or ''} {data.get('src_ip') or ''}:{data.get('src_port') or ''} "
            f"-> {data.get('dest_ip') or ''}:{data.get('dest_port') or ''}"
        )
        line = f"{_stamp(ts)} suricata: {text}"
        return Alert(ts, "suricata", level if isinstance(level, int) else None, _clip(line))
    host = str((raw.get("predecoder") or {}).get("hostname") or "")
    if not host:
        decoder = raw.get("decoder") or {}
        host = "suricata" if decoder.get("parent") == "snort" else "wazuh"
    full = str(raw.get("full_log") or "")
    line = (
        f"{_stamp(ts)} {host}: wazuh rule {rule.get('id', '')} level {level}: "
        f"{rule.get('description') or ''} {full}"
    )
    return Alert(ts, "wazuh", level if isinstance(level, int) else None, _clip(line))


def aminer_alert(raw: Mapping[str, Any]) -> Alert | None:
    """One record of ``<scenario>_aminer.json``: an anomaly AMiner found in a log line."""
    data = raw.get("LogData") or {}
    stamps = data.get("Timestamps") or []
    if not stamps:
        return None
    component = raw.get("AnalysisComponent") or {}
    lines = data.get("RawLogData") or [""]
    text = (
        f"{component.get('AnalysisComponentName') or 'AMiner'} "
        f"{component.get('Message') or ''}: {lines[0]}"
    )
    return Alert(
        float(stamps[0]), "aminer", None, _clip(f"{_stamp(float(stamps[0]))} aminer: {text}")
    )


def _read(bundle: zipfile.ZipFile, name: str, parse: Any) -> Iterator[Alert]:
    if name not in bundle.namelist():
        return
    with bundle.open(name) as raw, io.TextIOWrapper(raw, encoding="utf-8") as handle:
        for text in handle:
            if not text.strip():
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                continue
            alert = parse(record) if isinstance(record, Mapping) else None
            if alert is not None:
                yield alert


def iter_alerts(scenario: str, root: Path = AIT_DIR) -> Iterator[Alert]:
    """Every alert of a scenario in time order (each file is in time order; they are merged)."""
    archive = find(root)
    if archive is None:
        return
    with zipfile.ZipFile(archive) as bundle:
        yield from heapq.merge(
            _read(bundle, f"{scenario}_wazuh.json", wazuh_alert),
            _read(bundle, f"{scenario}_aminer.json", aminer_alert),
            key=lambda a: a.ts,
        )


@dataclass
class Window:
    scenario: str
    start: float
    end: float
    alerts: list[Alert]
    phases: tuple[str, ...]  # attack steps overlapping the window (the label)


def windows(
    alerts: Iterator[Alert], phases: list[Phase], scenario: str, minutes: int
) -> Iterator[Window]:
    """Contiguous windows of ``minutes``, holding at least one alert each, with the attack steps
    that overlap them. Alerts arrive in time order."""
    width = minutes * 60
    current: Window | None = None
    for alert in alerts:
        start = alert.ts - alert.ts % width
        if current is not None and start != current.start:
            yield current
            current = None
        if current is None:
            overlapping = tuple(
                sorted({p.name for p in phases if p.start < start + width and p.end >= start})
            )
            current = Window(scenario, start, start + width, [], overlapping)
        current.alerts.append(alert)
    if current is not None:
        yield current
