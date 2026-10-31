"""Whether ARIA's evidence holds the lines that say why a build failed, on LogChunks' CI logs.

LogChunks (Brandt, Panichella, Zaidman and Beller, MSR 2020): 797 failed Travis CI builds from 80
GitHub repositories in 29 languages, each with the chunk of its log that a person marked as the
reason the build failed. Build logs are not what ARIA was built for: they have no timestamps, no
nodes and few log levels, so this shows what a team gets from pointing ARIA at a kind of log it
was never tuned on.

Each build's log is triaged end to end offline, as any log would be, after the terminal's escape
codes and progress-bar rewrites are removed (as a terminal shows it). ARIA keeps a handful of raw
lines as evidence; a build counts as found when one of them lies inside the marked chunk.
Baselines keep the same number of lines from the same log with no model: the last lines, the last
lines that look like an error, and lines picked at random. A chunk that cannot be found in its
log (the label was trimmed or reworded) is counted and left out.
"""

from __future__ import annotations

import random
import re
import xml.etree.ElementTree as ET
import zlib
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aria.config import GuardrailConfig
from aria.contracts.inputs import RunOptions, TriageRequest
from aria.evals import metrics as m
from aria.evals.pipeline import EvalEnvironment

LOGCHUNKS_DIR = Path("data/raw/logchunks")
CITATION = (
    "C. E. Brandt, A. Panichella, A. Zaidman, M. Beller. LogChunks: A Data Set for Build Log "
    "Analysis. MSR 2020."
)
MISSING = {"missing": "download it with: aria data download --source logchunks"}
SYSTEM = "travis-ci"

_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]")
# The labels' XML could not keep the escape byte, so their colour codes lost it: "[31m".
_BARE_ESCAPE = re.compile(r"\[[0-9;]*[mK]")
_SPACE = re.compile(r"\s+")
_ERROR = re.compile(r"error|fail|exception|fatal|abort|denied|not found|cannot", re.IGNORECASE)


def clean(line: str) -> str:
    """A line as the terminal showed it: the last rewrite of the line, without escape codes."""
    shown = _ESCAPE.sub("", line.rstrip("\r").split("\r")[-1])
    return _SPACE.sub(" ", _BARE_ESCAPE.sub("", shown)).strip()


@dataclass(frozen=True)
class Build:
    log: str  # the log's path under logs/, as the labels name it
    language: str
    lines: list[str]  # the log's non-empty lines, cleaned
    chunk: tuple[int, int] | None  # first and last line of the marked chunk, if it was found
    category: str  # the label's structural category: 0, 1 or 2


def locate(lines: Sequence[str], chunk: str) -> tuple[int, int] | None:
    """The last place the chunk's first line starts with its last line close after it."""
    want = [c for c in (clean(line) for line in chunk.split("\n")) if c]
    if not want:
        return None
    reach = 3 * len(want) + 20
    for start in range(len(lines) - 1, -1, -1):
        if want[0] not in lines[start]:
            continue
        end = next(
            (k for k in range(start, min(len(lines), start + reach)) if want[-1] in lines[k]),
            None,
        )
        if end is not None:
            return start, end
    return None


def read_builds(root: Path = LOGCHUNKS_DIR) -> list[Build]:
    base = next((p for p in root.rglob("build-failure-reason") if p.is_dir()), None)
    if base is None:
        return []
    builds: list[Build] = []
    for labels in sorted(base.rglob("*.xml")):
        for example in ET.parse(labels).getroot():  # noqa: S314 - a pinned, checksummed download
            log = example.findtext("Log") or ""
            path = base.parent / "logs" / log
            if not log or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = [c for c in (clean(line) for line in text.split("\n")) if c]
            builds.append(
                Build(
                    log=log,
                    language=log.split("/", 1)[0],
                    lines=lines,
                    chunk=locate(lines, example.findtext("Chunk") or ""),
                    category=(example.findtext("Category") or "").strip(),
                )
            )
    return builds


def baselines(lines: Sequence[str], k: int, *, seed: int) -> dict[str, list[int]]:
    """``k`` lines picked with no model, as line numbers (0-based)."""
    errors = [i for i, line in enumerate(lines) if _ERROR.search(line)]
    picker = random.Random(seed)  # noqa: S311 - a baseline, not a secret
    return {
        "last_lines": list(range(max(0, len(lines) - k), len(lines))),
        "last_error_lines": errors[-k:] if k else [],
        "random_lines": sorted(picker.sample(range(len(lines)), min(k, len(lines)))),
    }


def _inside(picked: Sequence[int], chunk: tuple[int, int]) -> bool:
    return any(chunk[0] <= i <= chunk[1] for i in picked)


async def triage(
    env: EvalEnvironment,
    builds: Sequence[Build],
    *,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """One row per build whose chunk was found. Runs pause at review and are deleted once read,
    so builds can be shared out across processes in any order."""
    rows: list[dict[str, Any]] = []
    for n, build in enumerate(builds, 1):
        if build.chunk is None:
            continue
        outcome = await env.runner.start(
            TriageRequest(
                system=SYSTEM,
                title=f"Failed build {build.log}",
                logs=build.lines,
                options=RunOptions(use_llm=False),
            ),
            trigger="eval",
        )
        values = (await env.runner.snapshot(outcome.run_id)).values
        await env.runner.delete(outcome.run_id)
        kept = sorted(
            {
                int(e["data"]["line"]) - 1
                for e in values.get("evidence") or []
                if e.get("kind") == "log" and isinstance((e.get("data") or {}).get("line"), int)
            }
        )
        # Seeded by the build, so the random baseline does not depend on how builds are shared out.
        picks = baselines(build.lines, len(kept), seed=zlib.crc32(build.log.encode()))
        rows.append(
            {
                "log": build.log,
                "language": build.language,
                "category": build.category,
                "lines": len(build.lines),
                "chunk": list(build.chunk),
                "kept": kept,
                "found": _inside(kept, build.chunk),
                "baselines": {name: _inside(p, build.chunk) for name, p in picks.items()},
                "nearest": min((abs(i - build.chunk[0]) for i in kept), default=None),
            }
        )
        if progress and n % 50 == 0:
            progress(f"{n} of {len(builds)} builds")
    return rows


def _rate(hits: int, n: int) -> dict[str, Any]:
    return {
        "hits": hits,
        "rate": round(hits / n, 4) if n else 0.0,
        "ci95": m.exact_interval(hits, n),
    }


def summarize(rows: Sequence[dict[str, Any]], *, builds: int, located: int) -> dict[str, Any]:
    n = len(rows)
    kept = [len(r["kept"]) for r in rows]
    names = ("last_lines", "last_error_lines", "random_lines")
    cap = GuardrailConfig().max_lines
    return {
        "source": "LogChunks: failed Travis CI builds, each with the chunk that explains it",
        "citation": CITATION,
        "builds": builds,
        "located": located,
        "triaged": n,
        "languages": len({r["language"] for r in rows}),
        "over_line_cap": sum(1 for r in rows if r["lines"] > cap),
        "line_cap": cap,
        "median_lines": m.percentile([float(r["lines"]) for r in rows], 50) if rows else 0.0,
        "mean_kept": round(sum(kept) / n, 2) if n else 0.0,
        "aria": _rate(sum(r["found"] for r in rows), n),
        "baselines": {name: _rate(sum(r["baselines"][name] for r in rows), n) for name in names},
        "by_category": {
            category: _rate(sum(r["found"] for r in rows if r["category"] == category), count)
            for category, count in sorted(Counter(r["category"] for r in rows).items())
        },
        "nothing_kept": sum(1 for k in kept if k == 0),
    }
