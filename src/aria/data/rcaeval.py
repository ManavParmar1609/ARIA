"""RCAEval's RE3 suite (Pham et al., WWW 2025 Companion): code-level faults injected into
microservice shops, with the service each was injected into.

Each case is a folder ``<service>_<fault>/<repetition>`` inside ``RE3-<system>.zip``: every
service's logs (``logs.csv``: time, nanosecond timestamp, container, message, pod, node) from
about twelve minutes before the fault to about twelve minutes after, and ``inject_time.txt``,
the second the fault went in. The folder name is the label: the service at fault and the fault
type (f1 to f5, the dataset's own codes). ARIA reads the logs as a collector forwards them,
each line led by its time and its container's name; the folder name never reaches it.

Each case gives two windows: the logs before the fault (healthy) and the logs from the fault
on. The zips stay zipped; logs are read from inside them.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

RCAEVAL_DIR = Path("data/raw/rcaeval-re3")
RCAEVAL_CITATION = (
    "L. Pham, H. Zhang, H. Ha, F. Salim, X. Zhang. RCAEval: A Benchmark for Root Cause Analysis "
    "of Microservice Systems with Telemetry Data. WWW 2025 Companion. Zenodo, DOI "
    "10.5281/zenodo.14590730."
)
SYSTEMS = {"SS": "Sock Shop", "OB": "Online Boutique", "TT": "Train Ticket"}
_CASE = re.compile(r"^RE3-(?P<system>[A-Z]{2})/(?P<service>.+)_(?P<fault>f\d)/(?P<rep>\d+)/$")
MAX_LINE = 2_000


@dataclass(frozen=True)
class Case:
    system: str  # "SS", "OB" or "TT"
    service: str  # the service the fault was injected into (the label)
    fault: str  # "f1".."f5"
    repetition: str
    archive: Path
    folder: str  # "RE3-SS/carts_f1/1/"

    @property
    def id(self) -> str:
        return f"{self.system}/{self.service}_{self.fault}/{self.repetition}"


def find_cases(root: Path = RCAEVAL_DIR) -> list[Case]:
    """Every case with logs and an injection time, in every downloaded RE3 zip."""
    cases: list[Case] = []
    for archive in sorted(root.glob("RE3-*.zip")):
        with zipfile.ZipFile(archive) as bundle:
            names = set(bundle.namelist())
        folders = {n.rsplit("/", 1)[0] + "/" for n in names if n.endswith("/logs.csv")}
        for folder in sorted(folders):
            match = _CASE.match(folder)
            if match is None or f"{folder}inject_time.txt" not in names:
                continue
            cases.append(
                Case(
                    system=match["system"],
                    service=match["service"],
                    fault=match["fault"],
                    repetition=match["rep"],
                    archive=archive,
                    folder=folder,
                )
            )
    return cases


def inject_time(case: Case) -> float:
    with zipfile.ZipFile(case.archive) as bundle:
        return float(bundle.read(f"{case.folder}inject_time.txt").decode().strip())


def _stamp(nanoseconds: int) -> str:
    return datetime.fromtimestamp(nanoseconds / 1e9, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def iter_records(case: Case) -> Iterator[tuple[float, str, str]]:
    """(seconds since the epoch, container, line ARIA reads) for every log row, file order."""
    csv.field_size_limit(1 << 24)
    with (
        zipfile.ZipFile(case.archive) as bundle,
        bundle.open(f"{case.folder}logs.csv") as raw,
        io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="") as handle,
    ):
        for row in csv.DictReader(handle):
            stamp = (row.get("timestamp") or "").strip()
            if not stamp.isdigit():
                continue
            container = (row.get("container_name") or row.get("pod_name") or "app").strip()
            message = " ".join((row.get("message") or "").split())[:MAX_LINE]
            nanoseconds = int(stamp)
            yield nanoseconds / 1e9, container, f"{_stamp(nanoseconds)} {container}: {message}"


@dataclass
class CaseWindows:
    case: Case
    injected_at: float
    before: list[str]  # lines from before the fault, in time order
    after: list[str]  # lines from the fault on
    services_before: dict[str, int]  # lines per container
    services_after: dict[str, int]


def windows(case: Case) -> CaseWindows:
    """The case's logs split at the injection time, each half in time order."""
    at = inject_time(case)
    records = sorted(iter_records(case), key=lambda r: r[0])
    before = [r for r in records if r[0] < at]
    after = [r for r in records if r[0] >= at]

    def tally(rows: list[tuple[float, str, str]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for _, container, _ in rows:
            counts[container] = counts.get(container, 0) + 1
        return counts

    return CaseWindows(
        case=case,
        injected_at=at,
        before=[line for _, _, line in before],
        after=[line for _, _, line in after],
        services_before=tally(before),
        services_after=tally(after),
    )
