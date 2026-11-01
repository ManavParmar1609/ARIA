"""Nezha's Online Boutique data (Yu et al., ESEC/FSE 2023): faults injected into the shop's
pods over two days, with every service's logs.

The Zenodo record is one zip of two ``tar.xz`` archives, one per day, each holding the day's
fault list (the time, pod and type of every fault injected), per-minute log files, metrics and
traces, about 4 GB a day unpacked. ``aria data download`` never stores them: it streams each
archive out of the zip (checking it against the CRC-32 the zip records), keeps the fault list,
and keeps only the log files of the minutes near a fault, cut to the time, the pod and the
log record and gzipped (``<day>/log/HH_MM.tsv.gz``). A day's fault list is written last, once
its archive has been read to the end, so a day cut off part way is read again.

ARIA reads each fault as two windows, the service logs of the minutes before it and of the
minutes from it on, each line led by its time, level and service as a collector forwards it.
The fault list is the label: the pod the fault went into (so its service) and the fault's type.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import lzma
import re
import tarfile
import zlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import httpx

from aria.data import remote_zip
from aria.data.itbench import workload
from aria.data.loghub import normalize_level
from aria.data.manifest import DataSource

NEZHA_DIR = Path("data/raw/nezha")
NEZHA_CITATION = (
    "G. Yu, P. Chen, Y. Li, H. Chen, X. Li, Z. Zheng. Nezha: Interpretable Fine-Grained Root "
    "Causes Analysis for Microservices on Multi-Modal Observability Data. ESEC/FSE 2023. Zenodo, "
    "DOI 10.5281/zenodo.7029202."
)
FAULT_LIST = "fault_list.json"
_FAULT_FILE = re.compile(r"(\d{4}-\d{2}-\d{2})-fault_list\.json$")
_MINUTE_FILE = re.compile(r"/log/(\d{2})_(\d{2})_log\.csv$")
COLUMNS = ("ns", "pod", "log")
MAX_LINE = 2_000
# Fields of a service's JSON line that the line ARIA reads already shows.
_SHOWN = frozenset({"message", "msg", "severity", "level", "timestamp", "time", "ts"})


@dataclass(frozen=True)
class Fault:
    day: str  # "2022-08-22"
    folder: str  # where the day's files are, e.g. "dataset1"
    at: float  # the list's timestamp: seconds since the epoch, UTC
    pod: str
    kind: str  # e.g. "cpu_contention", "return", "exception"
    noted_at: float | None = None  # the list's readable time, which now and then differs

    @property
    def service(self) -> str:
        return workload(self.pod)

    @property
    def id(self) -> str:
        return f"{self.day}T{datetime.fromtimestamp(self.at, tz=UTC):%H:%M:%S} {self.service}"

    def spans(self, minutes: int) -> tuple[tuple[float, float], tuple[float, float]]:
        """(healthy, faulty): the ``minutes`` before the fault and the ``minutes`` from it on.

        Where the list's two times for a fault disagree, the healthy span ends at the earlier
        and the faulty one starts at the later, so neither holds logs the other should."""
        times = (self.at, self.noted_at if self.noted_at is not None else self.at)
        early, late = min(times), max(times)
        return (early - minutes * 60, early), (late, late + minutes * 60)


def _noted(value: Any) -> float | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC).timestamp()
    except ValueError:
        return None


def parse_faults(raw: Mapping[str, Any], day: str, folder: str) -> list[Fault]:
    """The faults of a day's fault list, which groups them by hour."""
    faults: list[Fault] = []
    for entries in raw.values():
        for entry in entries if isinstance(entries, list) else []:
            stamp = str(entry.get("inject_timestamp") or "")
            if not stamp.isdigit():
                continue
            faults.append(
                Fault(
                    day=day,
                    folder=folder,
                    at=float(stamp),
                    pod=str(entry.get("inject_pod") or ""),
                    kind=str(entry.get("inject_type") or "unknown"),
                    noted_at=_noted(entry.get("inject_time")),
                )
            )
    return sorted(faults, key=lambda f: f.at)


def find_faults(root: Path = NEZHA_DIR) -> list[Fault]:
    """Every fault of every downloaded day, in time order."""
    faults: list[Fault] = []
    for path in sorted(root.glob(f"*/{FAULT_LIST}")):
        meta = json.loads(path.read_text(encoding="utf-8"))
        faults += parse_faults(
            meta.get("faults") or {}, str(meta.get("day") or ""), path.parent.name
        )
    return sorted(faults, key=lambda f: f.at)


def minute_files(start: float, end: float) -> list[str]:
    """'HH_MM' of every log file that can hold a line from ``start`` to ``end``.

    A file holds about the minute before the time it is named for, so a line can be in the
    file of its own minute or of the next one."""
    first, last = int(start // 60), int(end // 60) + 1
    return [f"{datetime.fromtimestamp(m * 60, tz=UTC):%H_%M}" for m in range(first, last + 1)]


def _minutes_near(faults: list[Fault], minutes: int) -> set[str]:
    wanted: set[str] = set()
    for fault in faults:
        (start, _), (_, end) = fault.spans(minutes)
        wanted.update(minute_files(start, end))
    return wanted


def _value(value: Any) -> str:
    if isinstance(value, str) and value and not any(c.isspace() or c in '"=' for c in value):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def message(raw: str) -> tuple[str | None, str]:
    """(level, text) of one container log record: Docker's JSON around the service's own line,
    which is often JSON too (then its message comes first and its other fields follow)."""
    try:
        outer = json.loads(raw)
    except json.JSONDecodeError:
        return None, raw
    if not isinstance(outer, Mapping):
        return None, raw
    text = str(outer.get("log") or "").strip()
    if not text.startswith("{"):
        return None, text
    try:
        inner = json.loads(text)
    except json.JSONDecodeError:
        return None, text
    if not isinstance(inner, Mapping):
        return None, text
    level = inner.get("severity") or inner.get("level")
    body = str(inner.get("message") or inner.get("msg") or "")
    fields = " ".join(f"{k}={_value(v)}" for k, v in inner.items() if k not in _SHOWN)
    return normalize_level(str(level)) if level else None, " ".join(
        part for part in (body, fields) if part
    ) or text


@dataclass
class FaultWindows:
    fault: Fault
    before: list[str]
    after: list[str]
    services_before: dict[str, int]
    services_after: dict[str, int]


def _rows(path: Path) -> Iterator[list[str]]:
    csv.field_size_limit(1 << 24)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        next(reader, None)
        yield from reader


def windows(fault: Fault, root: Path = NEZHA_DIR, minutes: int = 1) -> FaultWindows:
    """The logs of the ``minutes`` before the fault and from it on, each in time order."""
    (start, early), (late, end) = fault.spans(minutes)
    seen: set[tuple[str, str, str]] = set()
    records: list[tuple[float, str, str]] = []
    for name in minute_files(start, end):
        path = root / fault.folder / "log" / f"{name}.tsv.gz"
        if not path.is_file():
            continue
        for row in _rows(path):
            if len(row) != len(COLUMNS) or not row[0].isdigit():
                continue
            seconds = int(row[0]) / 1e9
            if not (start <= seconds < early or late <= seconds < end):
                continue
            key = (row[0], row[1], row[2])
            if key in seen:
                continue  # neighbouring files can both hold a line
            seen.add(key)
            level, text = message(row[2])
            service = workload(row[1]) or "app"
            stamp = datetime.fromtimestamp(seconds, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            line = f"{stamp} {level + ' ' if level else ''}{service}: {' '.join(text.split())}"
            records.append((seconds, service, line[:MAX_LINE]))
    records.sort(key=lambda r: r[0])

    def tally(rows: list[tuple[float, str, str]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _, service, _ in rows:
            counts[service] = counts.get(service, 0) + 1
        return counts

    before = [r for r in records if r[0] < early]
    after = [r for r in records if r[0] >= late]
    return FaultWindows(
        fault=fault,
        before=[r[2] for r in before],
        after=[r[2] for r in after],
        services_before=tally(before),
        services_after=tally(after),
    )


# --- the download's stream reader -------------------------------------------------------------


class _Chunks(io.RawIOBase):
    """A file over an iterator of byte chunks (it cannot seek, so readers never try)."""

    def __init__(self, chunks: Iterator[bytes]) -> None:
        super().__init__()
        self._chunks = chunks
        self._pending = b""

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray | memoryview) -> int:  # type: ignore[override]
        while not self._pending:
            chunk = next(self._chunks, None)
            if chunk is None:
                return 0
            self._pending = chunk
        n = min(len(buffer), len(self._pending))
        buffer[:n] = self._pending[:n]
        self._pending = self._pending[n:]
        return n


def _write_minute(source: IO[bytes], target: Path) -> None:
    """A minute's log file cut to the time, the pod and the log record, gzipped."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    csv.field_size_limit(1 << 24)
    # A tar member read as a stream cannot say whether it seeks, so read it as plain chunks.
    plain = io.BufferedReader(_Chunks(iter(lambda: source.read(1 << 16), b"")), 1 << 16)
    with (
        io.TextIOWrapper(plain, encoding="utf-8", errors="replace", newline="") as text,
        partial.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as packed,
        io.TextIOWrapper(packed, encoding="utf-8", newline="") as handle,
    ):
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(COLUMNS)
        for row in csv.DictReader(text):
            writer.writerow(
                (row.get("TimeUnixNano") or "", row.get("PodName") or "", row.get("Log") or "")
            )
    partial.replace(target)


def read_archive(chunks: Iterator[bytes], dest: Path, folder: str, minutes: int) -> list[Path]:
    """Keep a day's fault list and the log files of the minutes near its faults.

    A log file that comes before the fault list in the archive is kept until the list is read,
    then dropped if no fault needs it. The fault list is written last, once the archive has
    been read to its end (and so checked)."""
    listed: tuple[str, Mapping[str, Any]] | None = None
    wanted: set[str] | None = None
    kept: dict[str, Path] = {}
    with (
        lzma.LZMAFile(io.BufferedReader(_Chunks(chunks), 1 << 20)) as archive,
        tarfile.open(fileobj=archive, mode="r|") as tar,
    ):
        for entry in tar:
            if not entry.isfile():
                continue
            day = _FAULT_FILE.search(entry.name)
            minute = _MINUTE_FILE.search(entry.name)
            if day is not None:
                handle = tar.extractfile(entry)
                raw = json.loads(handle.read()) if handle is not None else {}
                listed = (day.group(1), raw if isinstance(raw, Mapping) else {})
                wanted = _minutes_near(parse_faults(listed[1], listed[0], folder), minutes)
            elif minute is not None:
                name = f"{minute.group(1)}_{minute.group(2)}"
                handle = tar.extractfile(entry)
                if handle is None or (wanted is not None and name not in wanted):
                    continue
                target = dest / folder / "log" / f"{name}.tsv.gz"
                _write_minute(handle, target)
                kept[name] = target
    for _ in chunks:
        pass  # read the archive to its end, so its CRC-32 is checked
    if listed is None or wanted is None:
        msg = f"{folder}: the archive holds no fault list"
        raise ValueError(msg)
    for name in [n for n in kept if n not in wanted]:
        kept.pop(name).unlink()
    target = dest / folder / FAULT_LIST
    body = {"day": listed[0], "faults": listed[1]}
    target.write_text(json.dumps(body, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return [*sorted(kept.values()), target]


def write_minutes(
    source: DataSource, dest: Path, client: httpx.Client, url: str | None
) -> list[Path]:
    """Stream reader for ``aria data download``: each kept archive read once, as it streams."""
    from aria.data.download import DownloadError, throttle_for  # noqa: PLC0415 - import cycle

    stream = source.stream
    if stream is None or not url or not stream.keep or not stream.minutes:
        msg = f"{source.name}: the Nezha reader needs a URL, the archives to keep and minutes"
        raise DownloadError(msg)
    throttle = throttle_for(url)
    before = throttle.wait if throttle is not None else None
    written: list[Path] = []
    for name in stream.keep:
        folder = name.split(".", 1)[0]
        if (dest / folder / FAULT_LIST).is_file():
            continue  # read to its end on an earlier download
        member = remote_zip.locate(client, url, name, before=before)
        chunks = remote_zip.stream(client, url, member, before=before)
        try:
            written += read_archive(chunks, dest, folder, stream.minutes)
        except (
            ValueError,
            EOFError,
            tarfile.TarError,
            lzma.LZMAError,
            zlib.error,
            remote_zip.RemoteZipError,
        ) as exc:
            msg = f"{source.name}: {name} could not be read ({exc})"
            raise DownloadError(msg) from exc
    return written
