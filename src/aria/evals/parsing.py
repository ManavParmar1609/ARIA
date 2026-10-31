"""Template grouping accuracy against Loghub's hand-labelled event templates.

Every Loghub 2k sample ships a ground-truth event id per line. Grouping accuracy (Zhu et al.,
"Tools and Benchmarks for Automated Log Parsing", ICSE-SEIP 2019) counts a line as correct when
the lines ARIA groups with it are exactly the lines that share its ground-truth event. Lines go
through the production parser (redaction, injection guard, per-system Drain), rendered back to
raw text from the structured samples. A line the injection guard quarantines is never grouped,
so it counts as wrong, and real log lines flagged as injection are reported as false positives.

Loghub-2.0 (Jiang et al., "A Large-scale Evaluation for Log Parsing Techniques: How Far are We?",
ISSTA 2024) re-labelled 14 of the samples and fixed templates that merged or split real events.
When it is downloaded, the same parse is also scored against those corrected event ids, joined
by line id (only the ids are read; the lines themselves come from the original samples).

Loghub-2.0 also publishes whole logs with a ground-truth template for every line. Ten of them (Apache,
Hadoop, HealthApp, HPC, Linux, Mac, OpenSSH, OpenStack, Proxifier and Zookeeper) are scored the same
way, raw line by raw line, with grouping accuracy and the F1 grouping score Jiang et al. report
beside it, which counts every event the same however many lines it has.

GAIA (CloudWise's Generic AIOps Atlas) labels 10,000 lines from each of 14 systems with their
template. Nine are Loghub systems, parsed with the same settings; the other five (ArangoDB,
ClickHouse, Kafka, Redis, Tengine) have no format or Drain settings in ARIA, so they are parsed as
any system ARIA has never seen would be. Its lines are messages without their headers.
"""

from __future__ import annotations

import csv
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from aria.config import GuardrailConfig
from aria.data.loghub import LOGHUB_DIRS, format_raw_line, iter_structured_csv
from aria.evidence import EvidenceStore
from aria.parsing.parser import parse_lines

QUARANTINED = "<quarantined>"
GAIA_DIR = Path("data/raw/gaia-logs/log/log parsing/dataset")
GAIA_CITATION = (
    "CloudWise. GAIA (Generic AIOps Atlas), Companion Data: log parsing. "
    "github.com/CloudWise-OpenSource/GAIA-DataSet, 2021."
)
# GAIA's names for the systems ARIA has a format and Drain settings for; the rest are new to it.
GAIA_SYSTEMS = {
    "apache": "apache",
    "hadoop": "hadoop",
    "linux": "linux",
    "mac": "mac",
    "openstack": "openstack",
    "proxifier": "proxifier",
    "spark": "spark",
    "ssh": "openssh",
    "zookeeper": "zookeeper",
}
SALT = b"aria-eval-parsing"
CORRECTED_DIR = Path("data/raw/loghub2-corrected/2k_dataset")
LOGHUB2_DIR = Path("data/raw/loghub2-full")
LOGHUB2_CITATION = (
    "Z. Jiang, J. Liu, J. Huang, Y. Li, Y. Huo, J. Gu, Z. Chen, J. Zhu, M. R. Lyu. A Large-scale "
    "Evaluation for Log Parsing Techniques: How Far are We? ISSTA 2024."
)


def grouping_accuracy(predicted: Sequence[str], truth: Sequence[str]) -> float:
    """Share of lines whose predicted group equals their ground-truth group exactly."""
    if not truth:
        return 0.0
    groups: dict[str, set[int]] = defaultdict(set)
    events: dict[str, set[int]] = defaultdict(set)
    for i, (group, event) in enumerate(zip(predicted, truth, strict=True)):
        groups[group].add(i)
        events[event].add(i)
    correct = 0
    for group, members in groups.items():
        labels = {truth[i] for i in members}
        if group != QUARANTINED and len(labels) == 1 and events[labels.pop()] == members:
            correct += len(members)
    return correct / len(truth)


def group_f1(predicted: Sequence[str], truth: Sequence[str]) -> float:
    """F1 of grouping (Jiang et al., ISSTA 2024): a group counts when it holds exactly the lines of
    one ground-truth event. Precision is over ARIA's groups, recall over the events, so a rare
    event weighs as much as a common one."""
    groups: dict[str, set[int]] = defaultdict(set)
    events: dict[str, set[int]] = defaultdict(set)
    for i, (group, event) in enumerate(zip(predicted, truth, strict=True)):
        groups[group].add(i)
        events[event].add(i)
    exact = {frozenset(members) for members in events.values()}
    found = [g for g in groups if g != QUARANTINED]
    correct = sum(1 for g in found if frozenset(groups[g]) in exact)
    precision = correct / len(found) if found else 0.0
    recall = correct / len(events) if events else 0.0
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def corrected_events(directory: Path) -> dict[int, str]:
    """Loghub-2.0's corrected event id per line id, or nothing when it is not downloaded."""
    path = directory / f"{directory.name}_2k.log_structured_corrected.csv"
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {int(row["LineId"]): row["EventId"] for row in csv.DictReader(handle)}


def system_accuracy(
    directory: Path, system: str, corrected_dir: Path | None = None
) -> dict[str, Any] | None:
    """Parse one system's 2k sample and score it; None when the sample is not downloaded."""
    path = directory / f"{directory.name}_2k.log_structured.csv"
    if not path.exists():
        return None
    records = [r for r in iter_structured_csv(system, path) if r.gt_event_id]
    out = parse_lines(
        [format_raw_line(r) for r in records],
        system=system,
        guard=GuardrailConfig(max_lines=len(records) + 1),
        evidence=EvidenceStore(),
        salt=SALT,
    )
    predicted = [QUARANTINED] * len(records)
    for line in out.lines:
        predicted[line.idx] = line.template_id
    truth = [str(r.gt_event_id) for r in records]
    result: dict[str, Any] = {
        "lines": len(records),
        "events": len(set(truth)),
        "templates": len({p for p in predicted if p != QUARANTINED}),
        "grouping_accuracy": round(grouping_accuracy(predicted, truth), 4),
        "flagged_as_injection": len(out.quarantined),
    }
    fixed = corrected_events(corrected_dir / directory.name) if corrected_dir else {}
    pairs = [
        (p, fixed[r.line_no]) for p, r in zip(predicted, records, strict=True) if r.line_no in fixed
    ]
    if pairs:
        result["corrected_events"] = len({event for _, event in pairs})
        result["grouping_accuracy_corrected"] = round(
            grouping_accuracy([p for p, _ in pairs], [event for _, event in pairs]), 4
        )
    return result


def summarize(loghub_dir: Path, corrected_dir: Path = CORRECTED_DIR) -> dict[str, Any]:
    systems: dict[str, dict[str, Any]] = {}
    for name, system in sorted(LOGHUB_DIRS.items(), key=lambda kv: kv[1]):
        result = system_accuracy(loghub_dir / name, system, corrected_dir)
        if result is not None:
            systems[system] = result
    lines = sum(r["lines"] for r in systems.values())
    weighted = sum(r["grouping_accuracy"] * r["lines"] for r in systems.values())
    relabelled = {name: r for name, r in systems.items() if "grouping_accuracy_corrected" in r}
    corrected = [r["grouping_accuracy_corrected"] for r in relabelled.values()]
    return {
        "corrected": {
            "n_systems": len(corrected),
            "mean_grouping_accuracy": round(sum(corrected) / len(corrected), 4),
            # The original labels on the same systems, so the two means compare like for like.
            "original_mean_grouping_accuracy": round(
                sum(r["grouping_accuracy"] for r in relabelled.values()) / len(relabelled), 4
            ),
            "changed_systems": sorted(
                name
                for name, r in relabelled.items()
                if r["grouping_accuracy_corrected"] != r["grouping_accuracy"]
            ),
            "citation": (
                "Z. Jiang et al. A Large-scale Evaluation for Log Parsing Techniques: How Far are "
                "We? ISSTA 2024."
            ),
        }
        if corrected
        else None,
        "systems": systems,
        "n_systems": len(systems),
        "lines": lines,
        "mean_grouping_accuracy": round(
            sum(r["grouping_accuracy"] for r in systems.values()) / max(1, len(systems)), 4
        ),
        "line_weighted_grouping_accuracy": round(weighted / max(1, lines), 4),
        "real_lines_flagged_as_injection": sum(r["flagged_as_injection"] for r in systems.values()),
    }


def gaia_files(gaia_dir: Path = GAIA_DIR) -> dict[str, Path]:
    """Each system's labelled lines: ``<name>_result.csv``, or ``<name>.csv`` where GAIA left the
    suffix off; ``<name>_pattern.csv`` holds the templates themselves and is not needed."""
    return {
        path.stem.removesuffix("_result"): path
        for path in sorted(gaia_dir.glob("*.csv"))
        if not path.stem.endswith("_pattern")
    }


def _gaia_lines(path: Path) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    truth: list[str] = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for row in csv.DictReader(handle):
            message = (row.get("log_message") or "").strip("\r\n")
            if message and row.get("pattern_id") not in (None, ""):
                lines.append(message)
                truth.append(str(row["pattern_id"]))
    return lines, truth


def gaia_accuracy(path: Path, system: str) -> dict[str, Any]:
    lines, truth = _gaia_lines(path)
    out = parse_lines(
        lines,
        system=system,
        guard=GuardrailConfig(max_lines=len(lines) + 1),
        evidence=EvidenceStore(),
        salt=SALT,
    )
    predicted = [QUARANTINED] * len(lines)
    for line in out.lines:
        predicted[line.idx] = line.template_id
    return {
        "lines": len(lines),
        "events": len(set(truth)),
        "templates": len({p for p in predicted if p != QUARANTINED}),
        "grouping_accuracy": round(grouping_accuracy(predicted, truth), 4),
        # Grouping accuracy credits only exact groups: splitting a dominant event costs its share.
        "commonest_event_share": round(
            max(Counter(truth).values()) / len(truth) if truth else 0.0, 4
        ),
        "flagged_as_injection": len(out.quarantined),
    }


def _mean(results: Sequence[dict[str, Any]]) -> float:
    return round(sum(float(r["grouping_accuracy"]) for r in results) / max(1, len(results)), 4)


def summarize_gaia(gaia_dir: Path = GAIA_DIR) -> dict[str, Any]:
    files = gaia_files(gaia_dir)
    if not files:
        return {"missing": "download it with: aria data download --source gaia-logs"}
    systems: dict[str, dict[str, Any]] = {}
    for name, path in files.items():
        result = gaia_accuracy(path, GAIA_SYSTEMS.get(name, name))
        systems[name] = {**result, "aria_system": GAIA_SYSTEMS.get(name)}
    known = [r for r in systems.values() if r["aria_system"]]
    new = [r for r in systems.values() if not r["aria_system"]]
    return {
        "source": "GAIA's companion log-parsing data",
        "citation": GAIA_CITATION,
        "systems": systems,
        "n_systems": len(systems),
        "lines": sum(r["lines"] for r in systems.values()),
        "mean_grouping_accuracy": _mean(list(systems.values())),
        "known": {"n_systems": len(known), "mean_grouping_accuracy": _mean(known)},
        "new": {
            "n_systems": len(new),
            "mean_grouping_accuracy": _mean(new),
            "systems": sorted(name for name, r in systems.items() if not r["aria_system"]),
        },
        "real_lines_flagged_as_injection": sum(r["flagged_as_injection"] for r in systems.values()),
    }


def loghub2_dirs(root: Path = LOGHUB2_DIR) -> list[Path]:
    """The Loghub-2.0 systems downloaded under ``root`` that ARIA has a log format for."""
    if not root.exists():
        return []
    return [
        d
        for d in sorted(root.iterdir())
        if d.is_dir()
        and d.name in LOGHUB_DIRS
        and (d / f"{d.name}_full.log").exists()
        and (d / f"{d.name}_full.log_structured.csv").exists()
    ]


def loghub2_accuracy(directory: Path) -> dict[str, Any]:
    """Parse one system's whole Loghub-2.0 log, raw line by raw line, and score the groups."""
    started = time.perf_counter()
    name = directory.name
    with (directory / f"{name}_full.log_structured.csv").open(newline="", encoding="utf-8") as fh:
        truth = [str(row["EventId"]) for row in csv.DictReader(fh)]
    with (directory / f"{name}_full.log").open(encoding="utf-8", errors="replace") as handle:
        raw = [line.rstrip("\r\n") for line in handle]
    if len(raw) != len(truth):  # a log and its labels that disagree are not scored
        return {"lines": len(raw), "labels": len(truth), "error": "lines and labels differ"}
    out = parse_lines(
        raw,
        system=LOGHUB_DIRS[name],
        guard=GuardrailConfig(max_lines=len(raw) + 1),
        evidence=EvidenceStore(),
        salt=SALT,
    )
    predicted = [QUARANTINED] * len(raw)
    for line in out.lines:
        predicted[line.idx] = line.template_id
    return {
        "lines": len(raw),
        "events": len(set(truth)),
        "templates": len({p for p in predicted if p != QUARANTINED}),
        "grouping_accuracy": round(grouping_accuracy(predicted, truth), 4),
        "group_f1": round(group_f1(predicted, truth), 4),
        "flagged_as_injection": len(out.quarantined),
        "seconds": round(time.perf_counter() - started, 1),
    }


def summarize_loghub2(root: Path = LOGHUB2_DIR, *, workers: int = 1) -> dict[str, Any]:
    dirs = loghub2_dirs(root)
    if not dirs:
        return {"missing": "download it with: aria data download --source loghub2-full"}
    if workers > 1:
        with ProcessPoolExecutor(
            max_workers=min(workers, len(dirs)), mp_context=get_context("spawn")
        ) as executor:
            results = list(executor.map(loghub2_accuracy, dirs))
    else:
        results = [loghub2_accuracy(d) for d in dirs]
    systems = {
        d.name: {**r, "aria_system": LOGHUB_DIRS[d.name]}
        for d, r in zip(dirs, results, strict=True)
    }
    scored = [r for r in systems.values() if "error" not in r]
    lines = sum(r["lines"] for r in scored)
    return {
        "source": "Loghub-2.0 whole logs",
        "citation": LOGHUB2_CITATION,
        "systems": systems,
        "n_systems": len(scored),
        "lines": lines,
        "mean_grouping_accuracy": _mean(scored),
        "mean_group_f1": round(sum(r["group_f1"] for r in scored) / len(scored), 4)
        if scored
        else 0.0,
        # Weighted by lines, as a reader of the whole collection would meet them.
        "pooled_grouping_accuracy": round(
            sum(r["grouping_accuracy"] * r["lines"] for r in scored) / lines, 4
        )
        if lines
        else 0.0,
        "real_lines_flagged_as_injection": sum(r["flagged_as_injection"] for r in scored),
    }
