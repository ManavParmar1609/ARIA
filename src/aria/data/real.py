"""Real, labelled logs: lines as the system wrote them, labels from the system's experts.

Two uses share this module. The real-log evaluation (evals/real.py) replays the full HDFS sample
when it is downloaded. The console replays the small committed cut (tests/fixtures/real) as a
real incident: an ordinary run on real lines, with nothing composed or synthetic.
"""

from __future__ import annotations

import csv
import gzip
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from aria.data.loghub import LogRecord, format_raw_line, record_from_fields

HDFS_DIR = Path("data/raw/hdfs-100k")
HDFS_FIXTURE = Path("tests/fixtures/real/hdfs")
HDFS_CITATION = (
    "W. Xu, L. Huang, A. Fox, D. Patterson, M. I. Jordan. Detecting Large-Scale System Problems "
    "by Mining Console Logs. SOSP 2009."
)
_BLOCK = re.compile(r"blk_-?\d+")


@dataclass
class HdfsSample:
    records: list[LogRecord]
    anomalous: dict[str, bool]  # block id -> labelled Anomaly by the experts
    source: str
    fixture: bool
    blocks: dict[str, list[int]] = field(default_factory=dict)  # block id -> record indices

    def __post_init__(self) -> None:
        for i, rec in enumerate(self.records):
            for block in set(_BLOCK.findall(rec.message)):
                self.blocks.setdefault(block, []).append(i)


def _rows(path: Path) -> Iterator[dict[str, str]]:
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as raw, io.TextIOWrapper(raw, encoding="utf-8") as text:
            yield from csv.DictReader(text)
    else:
        with path.open(newline="", encoding="utf-8") as handle:
            yield from csv.DictReader(handle)


def load_hdfs(directory: Path, *, fixture: bool = False) -> HdfsSample | None:
    """The structured HDFS lines, in time order, and the experts' block labels, if present."""
    structured = next(
        (p for p in sorted(directory.rglob("*.log_structured.csv*")) if "HDFS" in p.name), None
    )
    labels_path = next(directory.rglob("anomaly_label.csv"), None)
    if structured is None or labels_path is None:
        return None
    records = [record_from_fields("hdfs", int(r["LineId"]), r) for r in _rows(structured)]
    records = sorted(
        (r for r in records if r.ts is not None),
        key=lambda r: (r.ts.timestamp() if r.ts else 0.0, r.line_no),
    )
    anomalous = {row["BlockId"]: row["Label"] == "Anomaly" for row in _rows(labels_path)}
    return HdfsSample(records, anomalous, source=str(structured), fixture=fixture)


def find_hdfs(hdfs_dir: Path = HDFS_DIR) -> HdfsSample | None:
    """The full sample when downloaded, otherwise the committed cut (not for measurement)."""
    return load_hdfs(hdfs_dir) or load_hdfs(HDFS_FIXTURE, fixture=True)


@dataclass(frozen=True)
class RealIncident:
    """A stretch of a real system's log that people can replay through ARIA."""

    id: str
    title: str
    system: str
    summary: str
    source: str
    citation: str
    directory: Path
    unit: str  # what the experts labelled, e.g. "block"

    @property
    def available(self) -> bool:
        return _sample(self.directory) is not None

    def lines(self) -> list[str]:
        """The raw lines, in the system's own format, as a run receives them."""
        sample = _sample(self.directory)
        return [format_raw_line(r) for r in sample.records] if sample else []

    def labels(self) -> dict[str, bool]:
        """Unit id -> whether the experts marked it failed."""
        sample = _sample(self.directory)
        return dict(sample.anomalous) if sample else {}

    def counts(self) -> tuple[int, int, int]:
        """Lines, labelled units in the cut, and how many of those the experts marked failed."""
        sample = _sample(self.directory)
        if sample is None:
            return 0, 0, 0
        labelled = [b for b in sample.blocks if b in sample.anomalous]
        return len(sample.records), len(labelled), sum(sample.anomalous[b] for b in labelled)


@cache
def _sample(directory: Path) -> HdfsSample | None:
    return load_hdfs(directory, fixture=True)


REAL_INCIDENTS: tuple[RealIncident, ...] = (
    RealIncident(
        id="hdfs-silent-block-failures",
        title="Silent block failures on a Hadoop cluster",
        system="hdfs",
        summary=(
            "Ten minutes of the log a Hadoop cluster of more than 200 nodes wrote in 2008: every "
            "line of one block in eight, in the order the cluster wrote them. Some storage blocks "
            "never finish being copied, and no line in the log is an error."
        ),
        source="Loghub HDFS_v1, the loglizer HDFS_100k sample; every line of one block in eight",
        citation=HDFS_CITATION,
        directory=HDFS_FIXTURE,
        unit="block",
    ),
)


def real_incident(incident_id: str) -> RealIncident | None:
    return next((i for i in REAL_INCIDENTS if i.id == incident_id), None)
