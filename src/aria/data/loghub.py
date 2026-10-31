"""Loghub systems: line formats, timestamps and level normalisation.

Line formats follow the logparser benchmark settings published with Loghub, so raw lines from the
full datasets and from users parse into the same fields as the structured 2k samples.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

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

    A field that only spaces part from the next field is one token. Were it free to hold spaces,
    a line that does not match (a wrapped warning, an indented dump) would try every way of
    sharing its spaces among those fields: minutes for one long OpenStack line, against the same
    fields on every line of the Loghub samples and the full BGL log.

    A message after plain spaces may be missing altogether: 0.7% of the full BGL log are
    lines such as "... RAS KERNEL FATAL" that end at the level.
    """
    parts = re.split(r"(<[^<>]+>)", log_format)
    single = {
        i
        for i in range(1, len(parts) - 2, 2)
        if (parts[i - 1].endswith(" ") or (i == 1 and not parts[0])) and parts[i + 1].isspace()
    }
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
            elif name == "Content":
                pattern += f"(?P<{name}>.*)"
            else:
                pattern += f"(?P<{name}>\\S+)" if i in single else f"(?P<{name}>.*?)"
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


# A line in no format ARIA knows: a timestamp it can read, if one leads the line; then a level,
# perhaps after a process or thread id ("148 INFO" in Hadoop's style, "[main] WARN"); then a
# component ending in a colon, perhaps after a thread ("[main] org.app.Server:") or with syslog's
# process id ("orders-svc[884]:"); then the message.
_LEVELS = "TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|ERR|SEVERE|CRITICAL|FATAL"
_GENERIC = re.compile(
    rf"^(?:(?:(?:\d+|\[[^\]]{{1,40}}\])\s+)?\[?(?P<level>{_LEVELS})\]?:?\s+)?"
    r"(?:(?:\[[^\]]{1,40}\]\s+)?\[?(?P<component>[\w.$/-]{2,80})(?:\[\d{1,10}\])?\]?:\s+)?"
    r"(?P<message>.*)$",
    re.IGNORECASE,
)


def _iso(text: str) -> datetime:
    return datetime.fromisoformat(text.replace(",", ".").replace("/", "-").replace(" ", "T"))


def _syslog(text: str) -> datetime:
    # Syslog leaves out the year; this year keeps durations and order, which is what counts.
    year = datetime.now(UTC).year
    stamp = f"{year} {' '.join(text.split())}"
    return datetime.strptime(stamp, "%Y %b %d %H:%M:%S").replace(tzinfo=UTC)


def _compact(text: str) -> datetime:
    return datetime.strptime(text, "%y%m%d %H%M%S").replace(tzinfo=UTC)


# Timestamps a line may start with, tried in turn: ISO 8601 (a space or a T, a dot or a comma
# before fractions, an optional zone, dashes or slashes), syslog's "Oct 31 10:00:01", and the
# compact "081109 203615" of Hadoop's logs.
_TIMESTAMPS: tuple[tuple[re.Pattern[str], Callable[[str], datetime]], ...] = (
    (
        re.compile(
            r"^\[?(\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?"
            r"(?:Z|[+-]\d{2}:?\d{2})?)\]?\s+"
        ),
        _iso,
    ),
    (re.compile(r"^([A-Z][a-z]{2} +\d{1,2} \d{2}:\d{2}:\d{2})\s+"), _syslog),
    (re.compile(r"^(\d{6} \d{6})\s+"), _compact),
)


# Times a line may carry elsewhere: an epoch in seconds or milliseconds as its first field
# ("1793416932840|ledger-sync|I|..."), the common log format's "[31/Oct/2026:02:00:00 +0000]"
# anywhere (web access logs), or an ISO time a few fields in.
_EPOCH = re.compile(r"^(\d{10}|\d{13})(?:[.,]\d+)?$")
_CLF_TIME = re.compile(r"\[(\d{2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2}(?: [+-]\d{4})?)\]")
_ISO_TIME = re.compile(
    r"(?<!\d)(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)(?!\d)"
)
# A level word a few fields in, as Kubernetes pods log it: "checkout-6b7c9d checkout INFO ...".
# Upper case only, so an ordinary word in a message is not read as one.
_LATE_LEVEL = re.compile(
    r"^(?:\S+\s+){1,3}?(?P<level>TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|ERR|SEVERE|"
    r"CRITICAL|FATAL)\s+\S"
)
# A web request's status in an access log: "GET /api HTTP/1.1" 502.
_ACCESS_STATUS = re.compile(
    r'"(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|CONNECT) [^"]*"\s+(?P<status>[1-5]\d\d)\b'
)
_NAME = re.compile(r"[A-Za-z][\w.$/-]{1,79}")


def _epoch_field(text: str) -> datetime | None:
    found = _EPOCH.match(text)
    if not found:
        return None
    value = int(found.group(1))
    seconds = value / 1000 if len(found.group(1)) == 13 else value
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _time_anywhere(text: str) -> datetime | None:
    clf = _CLF_TIME.search(text)
    if clf:
        try:
            return datetime.strptime(clf.group(1), "%d/%b/%Y:%H:%M:%S %z").astimezone(UTC)
        except ValueError:
            try:
                return datetime.strptime(clf.group(1), "%d/%b/%Y:%H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                return None
    iso = _ISO_TIME.search(text[:80])
    if iso:
        try:
            when = _iso(iso.group(1))
        except ValueError:
            return None
        return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)
    return None


def _delimited(text: str) -> tuple[datetime | None, str, str | None, str] | None:
    """A line of fields split by "|", one of the first four a level: the time, the level, the
    field before the level as the component, and the fields after it as the message."""
    parts = [part.strip() for part in text.split("|")]
    if len(parts) < 3:
        return None
    found = next(
        ((i, level) for i, part in enumerate(parts[:4]) if (level := normalize_level(part))), None
    )
    if found is None:
        return None
    at, level = found
    head = parts[:at]
    when = next(
        (t for t in (_epoch_field(part) or _time_anywhere(part) for part in head) if t), None
    )
    names = [part for part in head if _NAME.fullmatch(part)]
    message = " | ".join(part for part in parts[at + 1 :] if part)
    return when, level, (names[-1] if names else None), message or text


def parse_generic_line(system: str, line: str, line_no: int = 0) -> LogRecord:
    rest = line.strip()
    ts: datetime | None = None
    for pattern, read in _TIMESTAMPS:
        found = pattern.match(rest)
        if found:
            try:
                ts = read(found.group(1))
            except ValueError:
                break
            ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
            rest = rest[found.end() :]
            break
    delimited = _delimited(rest) if rest.count("|") >= 2 else None
    if delimited is not None:
        when, field_level, field_component, field_message = delimited
        return LogRecord(
            system=system,
            line_no=line_no,
            message=field_message,
            ts=ts or when,
            component=field_component,
            level=field_level,
            level_raw=field_level,
        )
    match = _GENERIC.match(rest)
    groups = match.groupdict() if match else {}
    message = (groups.get("message") or rest or line).strip()
    explicit = groups.get("level")
    component = groups.get("component")
    if not explicit and (late := _LATE_LEVEL.match(message)):
        # The level is read, the line is kept whole: what comes before it may be a pod and a
        # container, or the start of a sentence.
        explicit = late.group("level")
    level = normalize_level(explicit) or _derive_level(system, {}, message)
    status = None if explicit else _ACCESS_STATUS.search(message)
    if status is not None:
        # An access log has no level: a server error is an error, whatever words the path holds.
        level = "ERROR" if status.group("status").startswith("5") else "INFO"
    return LogRecord(
        system=system,
        line_no=line_no,
        message=message,
        ts=ts or _time_anywhere(rest),
        component=component,
        level=level,
        level_raw=explicit,
    )


def iter_structured_csv(system: str, path: Path, limit: int | None = None) -> Iterator[LogRecord]:
    """Read a Loghub ``*_structured.csv`` file into records."""
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        for i, row in enumerate(csv.DictReader(handle)):
            if limit is not None and i >= limit:
                return
            line_no = int(row.get("LineId") or i + 1)
            yield record_from_fields(system, line_no, row)


@contextmanager
def _open_text(path: Path, member: str | None) -> Iterator[TextIO]:
    if member is None:
        with path.open(encoding="utf-8", errors="replace") as handle:
            yield handle
        return
    with zipfile.ZipFile(path) as archive, archive.open(member) as raw:
        yield io.TextIOWrapper(raw, encoding="utf-8", errors="replace")


def iter_raw_log(
    system: str, path: Path, limit: int | None = None, *, member: str | None = None
) -> Iterator[LogRecord]:
    """Read a raw Loghub log; ``member`` reads one file inside the zip at ``path`` as it streams,
    so a log larger than the disk's free space never has to be extracted."""
    with _open_text(path, member) as handle:
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
