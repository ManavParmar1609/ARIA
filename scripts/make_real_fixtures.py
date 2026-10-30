"""Cut the real HDFS incident fixture from the full sample in data/raw/hdfs-100k.

Keeps every line of one block in eight (chosen by a hash of the block ID, so the cut is
reproducible) over ten busy minutes of the cluster's log, plus the few lines that name no block.
Sampling whole blocks keeps each block's life intact and keeps the share of failing blocks what
it was in the cluster, which matters: ARIA learns what a normal block looks like from the window
itself. Rows are unmodified, and the experts' label is kept for every block in the cut.

Run `uv run aria data download --source hdfs-100k` first.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

SRC = Path("data/raw/hdfs-100k/data/HDFS")
DST = Path("tests/fixtures/real/hdfs")
LICENSE = Path("data/raw/loghub-2k/LICENSE")
START_MIN, END_MIN = 2, 12  # minutes after the sample's first line
ONE_IN = 8
_BLOCK = re.compile(r"blk_-?\d+")


def _kept(block: str) -> bool:
    digest = hashlib.sha256(block.encode()).digest()
    return int.from_bytes(digest[:4], "big") % ONE_IN == 0


def _stamp(row: dict[str, str]) -> datetime:
    return datetime.strptime(row["Date"] + row["Time"], "%y%m%d%H%M%S").replace(tzinfo=UTC)


def main() -> None:
    with (SRC / "HDFS_100k.log_structured.csv").open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    first = _stamp(rows[0])
    start, end = first + timedelta(minutes=START_MIN), first + timedelta(minutes=END_MIN)
    keep = []
    for row in rows:
        if not start <= _stamp(row) < end:
            continue
        blocks = set(_BLOCK.findall(row["Content"]))
        if not blocks or any(_kept(b) for b in blocks):
            keep.append(row)
    blocks = {b for row in keep for b in _BLOCK.findall(row["Content"])}
    DST.mkdir(parents=True, exist_ok=True)
    out = DST / "HDFS_sample.log_structured.csv.gz"
    # mtime=0 keeps the archive byte-identical when the cut is regenerated.
    with (
        out.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz,
        io.TextIOWrapper(gz, encoding="utf-8", newline="") as text,
    ):
        writer = csv.DictWriter(text, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(keep)
    labels = {}
    with (SRC / "anomaly_label.csv").open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["BlockId"] in blocks:
                labels[row["BlockId"]] = row["Label"]
    with (DST / "anomaly_label.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["BlockId", "Label"])
        writer.writerows(sorted(labels.items()))
    shutil.copyfile(LICENSE, DST / "LICENSE")
    anomalous = sum(1 for v in labels.values() if v == "Anomaly")
    print(f"{out}: {len(keep)} lines, {len(blocks)} blocks, {anomalous} labelled Anomaly")


if __name__ == "__main__":
    main()
