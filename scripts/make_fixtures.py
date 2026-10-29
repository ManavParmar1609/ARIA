"""Build the small Loghub test fixtures from the official samples in data/raw/loghub-2k.

For each system in the scenario catalog, keep every BGL alert line, up to 40 lines per failure
mode, and up to 120 background lines, preserving the original rows.
Run `uv run aria data download --source loghub-2k` first.
"""

from __future__ import annotations

import csv
import shutil
from pathlib import Path

from aria.data.loghub import LOGHUB_DIRS
from aria.data.scenarios import load_catalog

SRC = Path("data/raw/loghub-2k")
DST = Path("tests/fixtures/loghub")
KEEP = 120
PER_MODE = 40


def main() -> None:
    modes = load_catalog()
    systems = {m.system for m in modes.values()}
    for directory, system in LOGHUB_DIRS.items():
        if system not in systems:
            continue
        src = SRC / directory / f"{directory}_2k.log_structured.csv"
        with src.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fieldnames = list(reader.fieldnames or [])
            rows = list(reader)
        system_modes = [m for m in modes.values() if m.system == system]

        def is_incident(row: dict[str, str], system_modes=system_modes) -> bool:
            if row.get("Label") not in (None, "", "-"):
                return True
            return any(
                m.pattern is not None and m.pattern.search(row["Content"]) for m in system_modes
            )

        chosen: dict[str, dict[str, str]] = {}
        for row in rows:
            if row.get("Label") not in (None, "", "-"):
                chosen[row["LineId"]] = row  # every ground-truth alert line
        for mode in system_modes:
            if mode.pattern is not None:
                for row in [r for r in rows if mode.pattern.search(r["Content"])][:PER_MODE]:
                    chosen[row["LineId"]] = row
        incident = list(chosen.values())
        background = [r for r in rows if not is_incident(r)][:KEEP]
        keep = sorted(incident + background, key=lambda r: int(r["LineId"]))
        out = DST / directory / f"{directory}_2k.log_structured.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(keep)
        print(
            f"{system:12s} {len(keep):4d} rows ({len(incident)} incident, {len(background)} background)"
        )
    shutil.copy(SRC / "LICENSE", DST / "LICENSE")


if __name__ == "__main__":
    main()
