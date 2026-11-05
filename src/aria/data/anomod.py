"""AnoMod (Ping et al., MSR 2026): anomalies injected into two microservice systems,
SocialNetwork (SN) and Train Ticket (TT), at four levels: performance, service, database and
code.

Each case is one run of the system with one anomaly active from the start of its workload to
its end (and one normal run per system), saved in a folder named after the anomaly. The folder
name is the label: its level, and for most cases the service it targets. ARIA reads only the
logs, as a collector forwards them: each line led by its time, its level and its service's name.
SocialNetwork logs every line of the run per service; Train Ticket keeps each pod's last 1,000
lines, stack traces included. A run's lines are merged in time order and ARIA reads the newest
``limit`` of them, as a scan at the end of the run would. The zip stays zipped.

Where a case's name names the service it targets, that service is the one to name: the killed
or stopped service, the service whose Redis cache was squeezed, or Train Ticket's preserve,
security and travel services. Cases whose name names no service (performance faults in
SocialNetwork, Train Ticket's database faults and its exception injection) are scored for
detection only.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ANOMOD_DIR = Path("data/raw/anomod")
ARCHIVE = "AnoMod.zip"
ANOMOD_CITATION = (
    "K. Ping, H. B. Mazhar, Y. Wang, Y. Song, M. V. Mäntylä. AnoMod: A Dataset for Anomaly "
    "Detection and Root Cause Analysis in Microservice Systems. MSR 2026. Zenodo, DOI "
    "10.5281/zenodo.18342898."
)
SYSTEMS = {"SN": "SocialNetwork", "TT": "Train Ticket"}
LEVELS = {
    "Perf": "performance",
    "Lv_P": "performance",
    "Svc": "service",
    "Lv_S": "service",
    "DB": "database",
    "Lv_D": "database",
    "Code": "code",
    "Lv_C": "code",
    "Normal": "normal",
}
# The service each case's name targets, where it names one (see the module docstring).
TARGETS = {
    "Svc_Kill_Media": "MediaService",
    "Svc_Kill_SocialGraph": "SocialGraphService",
    "Svc_Kill_UserTimeline": "UserTimelineService",
    "DB_Redis_CacheLimit_HomeTimeline": "HomeTimelineService",
    "DB_Redis_CacheLimit_SocialGraph": "SocialGraphService",
    "DB_Redis_CacheLimit_UserTimeline": "UserTimelineService",
    "Code_Stop_MediaService": "MediaService",
    "Code_Stop_TextService": "TextService",
    "Code_Stop_UserService": "UserService",
    "Lv_P_CPU_preserve": "ts-preserve-service",
    "Lv_P_DISKIO_preserve": "ts-preserve-service",
    "Lv_P_NETLOSS_preserve": "ts-preserve-service",
    "Lv_S_DNSFAIL_preserve_no_order": "ts-preserve-service",
    "Lv_S_HTTPABORT_preserve": "ts-preserve-service",
    "Lv_S_KILLPOD_preserve": "ts-preserve-service",
    "Lv_C_security_check": "ts-security-service",
    "Lv_C_travel_detail_failure": "ts-travel-service",
}
_SN_LINE = re.compile(
    r"^\[(?P<ts>\d{4}-[A-Z][a-z]{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)\]\s+<(?P<level>\w+)>:\s?(?P<msg>.*)$"
)
_TT_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+(?P<level>[A-Z]+)\s+(?P<msg>.*)$"
)
_TT_AGENT = re.compile(
    r"^(?P<level>TRACE|DEBUG|INFO|WARN|ERROR)\s+"
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}):(?P<ms>\d{3})\s+(?P<msg>.*)$"
)
_CASE_NAME = re.compile(r"^(?P<name>.+?)_(?:em_)?\d{8}[T_]\d{6}Z?(?:_em)?(?:_logs_.*)?$")
_POD_FILE = re.compile(r"^(?P<pod>.+?)(?:_previous)?_\d{8}_\d{6}\.log$")
_POD_HASH = re.compile(r"-[0-9a-f]{6,10}-[0-9a-z]{5}$")
_ORDINAL = re.compile(r"-\d+$")
_LEVEL_WORDS = {"warning": "WARN", "warn": "WARN", "err": "ERROR", "critical": "FATAL"}
MAX_LINE = 2_000


@dataclass(frozen=True)
class Case:
    system: str  # "SN" or "TT"
    name: str  # the anomaly's name, e.g. "Svc_Kill_Media"
    folder: str  # the case's log folder inside the zip

    @property
    def level(self) -> str:
        for prefix, level in LEVELS.items():
            if self.name.startswith(prefix):
                return level
        return "unknown"

    @property
    def anomalous(self) -> bool:
        return self.level != "normal"

    @property
    def target(self) -> str | None:
        return TARGETS.get(self.name)


def find(root: Path = ANOMOD_DIR) -> Path | None:
    archive = root / ARCHIVE
    return archive if archive.is_file() else None


def find_cases(root: Path = ANOMOD_DIR) -> list[Case]:
    archive = find(root)
    if archive is None:
        return []
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    cases: dict[str, Case] = {}
    for name in names:
        parts = name.split("/")
        if len(parts) < 4 or parts[1] != "log_data" or not parts[0].endswith("_data"):
            continue
        system = parts[0].removesuffix("_data")
        match = _CASE_NAME.match(parts[2])
        if system not in SYSTEMS or match is None:
            continue
        folder = "/".join(parts[:3]) + "/"
        cases.setdefault(folder, Case(system=system, name=match["name"], folder=folder))
    return sorted(cases.values(), key=lambda c: (c.system, c.name))


def _level(word: str) -> str:
    word = word.lower()
    return _LEVEL_WORDS.get(word, word.upper())


def _service_of(path: str, system: str) -> str:
    file = path.rsplit("/", 1)[-1]
    if system == "SN":
        return file.removesuffix(".log").rstrip("_")
    match = _POD_FILE.match(file)
    pod = match["pod"] if match else file.removesuffix(".log")
    if _POD_HASH.search(pod):  # a Deployment's pod: ts-order-service-86d6f7876-6ghzm
        return _POD_HASH.sub("", pod)
    return _ORDINAL.sub("", pod)  # a StatefulSet's: nacosdb-mysql-0


def _parse(line: str, system: str) -> tuple[datetime, str, str] | None:
    """(time in UTC, level, message) of a line that starts a record, else None."""
    if system == "SN":
        found = _SN_LINE.match(line)
        if found is None:
            return None
        when = datetime.strptime(found["ts"], "%Y-%b-%d %H:%M:%S.%f").replace(tzinfo=UTC)
        return when, _level(found["level"]), found["msg"]
    found = _TT_LINE.match(line)
    if found is not None:
        # Train Ticket's pods log in UTC+8; times move to UTC so a run reads in one zone.
        local = datetime.strptime(f"{found['ts']}+0800", "%Y-%m-%d %H:%M:%S.%f%z")
        return local.astimezone(UTC), _level(found["level"]), found["msg"]
    agent = _TT_AGENT.match(line)
    if agent is not None:
        stamp = f"{agent['ts']}.{agent['ms']}+0800"
        local = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S.%f%z")
        return local.astimezone(UTC), _level(agent["level"]), agent["msg"]
    return None


def case_lines(case: Case, root: Path = ANOMOD_DIR, limit: int | None = None) -> list[str]:
    """The run's log lines in time order, each led by its time, level and service; a stack
    trace stays with the line that started it. ``limit`` keeps the newest lines."""
    archive = find(root)
    if archive is None:
        return []
    groups: list[tuple[datetime, int, list[str]]] = []
    order = 0
    with zipfile.ZipFile(archive) as bundle:
        for name in sorted(bundle.namelist()):
            if not (name.startswith(case.folder) and name.endswith(".log")):
                continue
            service = _service_of(name, case.system)
            current: list[str] | None = None
            text = bundle.read(name).decode("utf-8", errors="replace")
            for raw in text.splitlines():
                parsed = _parse(raw, case.system)
                if parsed is not None:
                    when, level, message = parsed
                    stamp = when.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                    current = [f"{stamp} {level} {service}: {' '.join(message.split())}"[:MAX_LINE]]
                    groups.append((when, order, current))
                    order += 1
                elif current is not None and raw.strip():
                    current.append(" ".join(raw.split())[:MAX_LINE])
    groups.sort(key=lambda g: (g[0], g[1]))
    lines = [line for _, _, group in groups for line in group]
    return lines[-limit:] if limit is not None else lines
