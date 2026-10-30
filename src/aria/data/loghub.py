"""Loghub systems: line formats, timestamps and level normalisation.

Line formats follow the logparser benchmark settings published with Loghub, so raw lines from the
full datasets and from users parse into the same fields as the structured 2k samples.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

CANONICAL_LEVELS = ("DEBUG", "INFO", "WARN", "ERROR", "FATAL")
_LEVEL_MAP = {
    "TRACE": "DEBUG",
    "DEBUG": "DEBUG",
    "D": "DEBUG",
    "V": "DEBUG",
    "VERBOSE": "DEBUG",
    "INFO": "INFO",
    "I": "INFO",
    "NOTICE": "INFO",
    "WARN": "WARN",
    "WARNING": "WARN",
    "W": "WARN",
    "ERROR": "ERROR",
    "ERR": "ERROR",
    "E": "ERROR",
    "SEVERE": "ERROR",
    "CRIT": "FATAL",
    "CRITICAL": "FATAL",
    "ALERT": "FATAL",
    "EMERG": "FATAL",
    "FATAL": "FATAL",
    "FAILURE": "FATAL",
    "F": "FATAL",
}


def normalize_level(raw: str | None) -> str | None:
    if not raw:
        return None
    return _LEVEL_MAP.get(raw.strip().upper())


@dataclass(frozen=True, slots=True)
class SystemSpec:
    name: str
    log_format: str
    default_year: int
    node_field: str | None = None
    component_field: str | None = "Component"
    level_field: str | None = "Level"
    labelled: bool = False
    description: str = ""
    regex: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "regex", format_to_regex(self.log_format))


def format_to_regex(log_format: str) -> re.Pattern[str]:
    """Turn '<Date> <Time> <Level> <Component>: <Content>' into a named-group regex.

    A message after plain spaces may be missing altogether: 0.7% of the full BGL log are
    lines such as "... RAS KERNEL FATAL" that end at the level.
    """
    parts = re.split(r"(<[^<>]+>)", log_format)
    if len(parts) >= 3 and parts[-2:] == ["<Content>", ""] and parts[-3] and not parts[-3].strip():
        parts[-3:] = ["", "<OptionalContent>", ""]  # the spaces move inside the optional group
    pattern = ""
    for i, part in enumerate(parts):
        if i % 2 == 0:
            pattern += re.sub(r" +", r"\\s+", part)
        else:
            name = part.strip("<>")
            if name == "OptionalContent":
                pattern += r"(?:\s+(?P<Content>.*))?"
            else:
                pattern += f"(?P<{name}>.*)" if name == "Content" else f"(?P<{name}>.*?)"
    return re.compile(f"^{pattern}$")


SYSTEMS: dict[str, SystemSpec] = {
    spec.name: spec
    for spec in (
        SystemSpec(
            "bgl",
            "<Label> <Timestamp> <Date> <Node> <Time> <NodeRepeat> <Type> <Component> <Level> <Content>",
            2005,
            node_field="Node",
            labelled=True,
            description="BlueGene/L supercomputer (LLNL)",
        ),
        SystemSpec(
            "thunderbird",
            r"<Label> <Timestamp> <Date> <User> <Month> <Day> <Time> <Location> <Component>(\[<PID>\])?: <Content>",
            2005,
            node_field="Location",
            level_field=None,
            labelled=True,
            description="Thunderbird supercomputer (Sandia)",
        ),
        SystemSpec(
            "hdfs",
            "<Date> <Time> <Pid> <Level> <Component>: <Content>",
            2008,
            description="Hadoop distributed file system",
        ),
        SystemSpec(
            "hadoop",
            r"<Date> <Time> <Level> \[<Process>\] <Component>: <Content>",
            2015,
            description="Hadoop MapReduce",
        ),
        SystemSpec(
            "spark",
            "<Date> <Time> <Level> <Component>: <Content>",
            2017,
            description="Apache Spark",
        ),
        SystemSpec(
            "zookeeper",
            r"<Date> <Time> - <Level>  \[<Node>:<Component>@<Id>\] - <Content>",
            2015,
            node_field="Node",
            description="Apache ZooKeeper",
        ),
        SystemSpec(
            "openstack",
            r"<Logrecord> <Date> <Time> <Pid> <Level> <Component> \[<ADDR>\] <Content>",
            2017,
            node_field="ADDR",
            description="OpenStack Nova",
        ),
        SystemSpec(
            "hpc",
            "<LogId> <Node> <Component> <State> <Time> <Flag> <Content>",
            2004,
            node_field="Node",
            level_field=None,
            description="HPC cluster (LANL)",
        ),
        SystemSpec(
            "windows",
            "<Date> <Time>, <Level>                  <Component>    <Content>",
            2016,
            description="Windows CBS",
        ),
        # Linux: the column Loghub names "Level" holds the host name.
        SystemSpec(
            "linux",
            r"<Month> <Date> <Time> <Level> <Component>(\[<PID>\])?: <Content>",
            2005,
            node_field="Level",
            level_field=None,
            description="Linux syslog",
        ),
        SystemSpec(
            "mac",
            r"<Month>  <Date> <Time> <User> <Component>\[<PID>\]( \(<Address>\))?: <Content>",
            2017,
            node_field="User",
            level_field=None,
            description="macOS system log",
        ),
        SystemSpec(
            "android",
            "<Date> <Time>  <Pid>  <Tid> <Level> <Component>: <Content>",
            2017,
            description="Android framework",
        ),
        SystemSpec(
            "healthapp",
            r"<Time>\|<Component>\|<Pid>\|<Content>",
            2017,
            level_field=None,
            description="Health app",
        ),
        SystemSpec(
            "apache",
            r"\[<Time>\] \[<Level>\] <Content>",
            2005,
            component_field=None,
            description="Apache HTTP server error log",
        ),
        # In OpenSSH logs the <Component> column is the host name, so it is the node.
        SystemSpec(
            "openssh",
            r"<Date> <Day> <Time> <Component> sshd\[<Pid>\]: <Content>",
            2017,
            node_field="Component",
            component_field=None,
            level_field=None,
            description="OpenSSH server",
        ),
        SystemSpec(
            "proxifier",
            r"\[<Time>\] <Program> - <Content>",
            2017,
            component_field="Program",
            level_field=None,
            description="Proxifier client",
        ),
    )
}

# Loghub directory names differ in case from ARIA's system ids.
LOGHUB_DIRS = {
    "BGL": "bgl",
    "Thunderbird": "thunderbird",
    "HDFS": "hdfs",
    "Hadoop": "hadoop",
    "Spark": "spark",
    "Zookeeper": "zookeeper",
    "OpenStack": "openstack",
    "HPC": "hpc",
    "Windows": "windows",
    "Linux": "linux",
    "Mac": "mac",
    "Android": "android",
    "HealthApp": "healthapp",
    "Apache": "apache",
    "OpenSSH": "openssh",
    "Proxifier": "proxifier",
}

_DROP_FIELDS = frozenset({"Content", "EventTemplate", "EventId", "LineId"})
_MONTHS = {
    m: i
    for i, m in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}


@dataclass(slots=True)
class LogRecord:
    system: str
    line_no: int
    message: str
    ts: datetime | None = None
    node: str | None = None
    component: str | None = None
    level: str | None = None
    level_raw: str | None = None
    label: str | None = None
    gt_template: str | None = None
    gt_event_id: str | None = None
    fields: dict[str, str] = field(default_factory=dict)


def _try(fmt: str, value: str) -> datetime | None:
    try:
        return datetime.strptime(value, fmt).replace(tzinfo=UTC)
    except ValueError:
        return None


def _epoch(value: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (ValueError, OverflowError, OSError):
        return None


def parse_timestamp(system: str, fields: dict[str, str]) -> datetime | None:
    """Best-effort UTC timestamp. Logs without a year use the dataset's collection year."""
    spec = SYSTEMS.get(system)
    year = spec.default_year if spec else 2020
    get = fields.get
    match system:
        case "bgl" | "thunderbird":
            return _epoch(get("Timestamp", ""))
        case "hpc":
            return _epoch(get("Time", ""))
        case "hdfs":
            return _try("%y%m%d%H%M%S", get("Date", "").zfill(6) + get("Time", "").zfill(6))
        case "hadoop" | "zookeeper":
            return _try("%Y-%m-%d %H:%M:%S,%f", f"{get('Date', '')} {get('Time', '')}")
        case "spark":
            return _try("%y/%m/%d %H:%M:%S", f"{get('Date', '')} {get('Time', '')}")
        case "openstack":
            return _try("%Y-%m-%d %H:%M:%S.%f", f"{get('Date', '')} {get('Time', '')}")
        case "windows":
            return _try("%Y-%m-%d %H:%M:%S", f"{get('Date', '')} {get('Time', '')}")
        case "apache":
            return _try("%a %b %d %H:%M:%S %Y", get("Time", ""))
        case "healthapp":
            return _try("%Y%m%d-%H:%M:%S:%f", get("Time", ""))
        case "android":
            return _try("%Y-%m-%d %H:%M:%S.%f", f"{year}-{get('Date', '')} {get('Time', '')}")
        case "proxifier":
            return _try("%Y.%m.%d %H:%M:%S", f"{year}.{get('Time', '')}")
        case "linux" | "mac":
            month = _MONTHS.get(get("Month", ""))
            return (
                _try("%Y-%m-%d %H:%M:%S", f"{year}-{month}-{get('Date', '')} {get('Time', '')}")
                if month
                else None
            )
        case "openssh":
            month = _MONTHS.get(get("Date", ""))
            return (
                _try("%Y-%m-%d %H:%M:%S", f"{year}-{month}-{get('Day', '')} {get('Time', '')}")
                if month
                else None
            )
        case _:
            return None


def _derive_level(system: str, fields: dict[str, str], message: str) -> str | None:
    """Systems without a level column get one from well-known markers in the message."""
    if system == "hpc":
        state = fields.get("State", "").lower()
        if "unavailable" in state or "down" in state:
            return "ERROR"
    lowered = message.lower()
    if any(w in lowered for w in ("panic", "fatal", "kernel terminated")):
        return "FATAL"
    if any(w in lowered for w in ("error", "failed", "failure", "exception", "refused", "denied")):
        return "ERROR"
    if any(w in lowered for w in ("warn", "timeout", "timed out", "retry")):
        return "WARN"
    return "INFO"


def _split_zookeeper(node: str | None, component: str | None) -> tuple[str | None, str | None]:
    """ZooKeeper logs ``[thread:Class@line]`` and thread names hold colons of their own
    (``QuorumPeer[myid=1]/0:0:0:0:0:0:0:0:2181``). Loghub's split, at the first colon, leaves
    part of the thread in the component; the class is the last part, the rest is the thread."""
    if not component or ":" not in component:
        return node, component
    prefix, _, component = component.rpartition(":")
    thread = ":".join(part for part in (node, prefix) if part).rstrip(":")
    return thread or None, component or None


def record_from_fields(system: str, line_no: int, fields: dict[str, str]) -> LogRecord:
    spec = SYSTEMS[system]
    message = fields.get("Content", "").strip()
    level_raw = fields.get(spec.level_field, "") if spec.level_field else ""
    level = normalize_level(level_raw) or _derive_level(system, fields, message)
    label = fields.get("Label")
    node = (fields.get(spec.node_field) or None) if spec.node_field else None
    component = (fields.get(spec.component_field) or None) if spec.component_field else None
    if system == "zookeeper":
        node, component = _split_zookeeper(node, component)
    return LogRecord(
        system=system,
        line_no=line_no,
        message=message,
        ts=parse_timestamp(system, fields),
        node=node,
        component=component,
        level=level,
        level_raw=level_raw or None,
        label=None if label in (None, "", "-") else label,
        gt_template=fields.get("EventTemplate") or None,
        gt_event_id=fields.get("EventId") or None,
        fields={k: v for k, v in fields.items() if k not in _DROP_FIELDS},
    )


def parse_raw_line(system: str, line: str, line_no: int = 0) -> LogRecord:
    """Parse one raw line. Unknown systems, or lines that don't match, keep the whole line."""
    spec = SYSTEMS.get(system)
    if spec is not None:
        match = spec.regex.match(line.rstrip("\n"))
        if match:
            fields = {k: (v or "").strip() for k, v in match.groupdict().items()}
            return record_from_fields(system, line_no, fields)
    return parse_generic_line(system, line, line_no)


_GENERIC = re.compile(
    r"^(?:(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+)?"
    r"(?:\[?(?P<level>TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|ERR|SEVERE|CRITICAL|FATAL)\]?\s+)?"
    r"(?:\[?(?P<component>[\w.$/-]{2,80})\]?:\s+)?(?P<message>.*)$",
    re.IGNORECASE,
)


def parse_generic_line(system: str, line: str, line_no: int = 0) -> LogRecord:
    match = _GENERIC.match(line.strip())
    groups = match.groupdict() if match else {}
    ts: datetime | None = None
    if groups.get("ts"):
        try:
            ts = datetime.fromisoformat(groups["ts"].replace(",", ".").replace(" ", "T"))
            ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
        except ValueError:
            ts = None
    message = (groups.get("message") or line).strip()
    level = normalize_level(groups.get("level")) or _derive_level(system, {}, message)
    return LogRecord(
        system=system,
        line_no=line_no,
        message=message,
        ts=ts,
        component=groups.get("component"),
        level=level,
        level_raw=groups.get("level"),
    )


def iter_structured_csv(system: str, path: Path, limit: int | None = None) -> Iterator[LogRecord]:
    """Read a Loghub ``*_structured.csv`` file into records."""
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        for i, row in enumerate(csv.DictReader(handle)):
            if limit is not None and i >= limit:
                return
            line_no = int(row.get("LineId") or i + 1)
            yield record_from_fields(system, line_no, row)


def iter_raw_log(system: str, path: Path, limit: int | None = None) -> Iterator[LogRecord]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for i, line in enumerate(handle):
            if limit is not None and i >= limit:
                return
            if line.strip():
                yield parse_raw_line(system, line, i + 1)


def format_raw_line(record: LogRecord) -> str:
    """Render a record in its system's raw line format, so it parses back to the same fields.

    Time and node come from the record (the scenario builder rewrites them); every other field
    keeps the value from the original Loghub line.
    """
    f = record.fields
    ts = record.ts or datetime(2020, 1, 1, tzinfo=UTC)
    node = record.node or "node-0"
    msg = record.message
    ms = f"{ts.microsecond // 1000:03d}"

    def get(name: str, default: str) -> str:
        return f.get(name) or default

    match record.system:
        case "bgl":
            stamp = ts.strftime("%Y-%m-%d-%H.%M.%S.%f")
            return (
                f"{record.label or '-'} {int(ts.timestamp())} {ts:%Y.%m.%d} {node} {stamp} {node} "
                f"{get('Type', 'RAS')} {get('Component', 'KERNEL')} {get('Level', 'INFO')} {msg}"
            )
        case "thunderbird":
            user = node.split("/", 1)[0]
            pid = f"[{f['PID']}]" if f.get("PID") else ""
            return (
                f"{record.label or '-'} {int(ts.timestamp())} {ts:%Y.%m.%d} {user} {ts:%b} {ts.day} "
                f"{ts:%H:%M:%S} {node} {get('Component', 'kernel')}{pid}: {msg}"
            )
        case "hdfs":
            return f"{ts:%y%m%d} {ts:%H%M%S} {get('Pid', '143')} {get('Level', 'INFO')} {get('Component', 'dfs.DataNode')}: {msg}"
        case "hadoop":
            return f"{ts:%Y-%m-%d %H:%M:%S},{ms} {get('Level', 'INFO')} [{get('Process', 'main')}] {get('Component', 'app')}: {msg}"
        case "spark":
            return (
                f"{ts:%y/%m/%d %H:%M:%S} {get('Level', 'INFO')} {get('Component', 'spark')}: {msg}"
            )
        case "zookeeper":
            # The record holds the normalised thread (as node) and class; see _split_zookeeper.
            component = record.component or get("Component", "Server")
            return f"{ts:%Y-%m-%d %H:%M:%S},{ms} - {get('Level', 'INFO')}  [{node}:{component}@{get('Id', '100')}] - {msg}"
        case "openstack":
            return f"{get('Logrecord', 'nova-compute.log')} {ts:%Y-%m-%d %H:%M:%S}.{ms} {get('Pid', '2931')} {get('Level', 'INFO')} {get('Component', 'nova.compute')} [{node}] {msg}"
        case "hpc":
            return f"{get('LogId', '1')} {node} {get('Component', 'unix.hw')} {get('State', 'state_change')} {int(ts.timestamp())} {get('Flag', '1')} {msg}"
        case "windows":
            return f"{ts:%Y-%m-%d %H:%M:%S}, {get('Level', 'Info')}                  {get('Component', 'CBS')}    {msg}"
        case "linux":
            pid = f"[{f['PID']}]" if f.get("PID") else ""
            return (
                f"{ts:%b} {ts.day:2d} {ts:%H:%M:%S} {node} {get('Component', 'kernel')}{pid}: {msg}"
            )
        case "mac":
            address = f" ({f['Address']})" if f.get("Address") else ""
            return f"{ts:%b} {ts.day:2d} {ts:%H:%M:%S} {node} {get('Component', 'kernel')}[{get('PID', '0')}]{address}: {msg}"
        case "android":
            return f"{ts:%m-%d %H:%M:%S}.{ms}  {get('Pid', '1702')}  {get('Tid', '2395')} {get('Level', 'I')} {get('Component', 'System')}: {msg}"
        case "healthapp":
            return f"{ts:%Y%m%d-%H:%M:%S}:{ms}|{get('Component', 'Step_LSC')}|{get('Pid', '30002312')}|{msg}"
        case "apache":
            return f"[{ts:%a %b %d %H:%M:%S %Y}] [{get('Level', 'notice')}] {msg}"
        case "openssh":
            return f"{ts:%b} {ts.day:2d} {ts:%H:%M:%S} {node} sshd[{get('Pid', '24200')}]: {msg}"
        case "proxifier":
            return f"[{ts:%m.%d %H:%M:%S}] {get('Program', 'chrome.exe')} - {msg}"
        case _:
            return f"{ts.isoformat()} {record.level or 'INFO'} {record.component or 'app'}: {msg}"
