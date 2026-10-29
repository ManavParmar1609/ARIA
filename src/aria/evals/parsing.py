"""Template grouping accuracy against Loghub's hand-labelled event templates.

Every Loghub 2k sample ships a ground-truth event id per line. Grouping accuracy (Zhu et al.,
"Tools and Benchmarks for Automated Log Parsing", ICSE-SEIP 2019) counts a line as correct when
the lines ARIA groups with it are exactly the lines that share its ground-truth event. Lines go
through the production parser (redaction, injection guard, per-system Drain), rendered back to
raw text from the structured samples. A line the injection guard quarantines is never grouped,
so it counts as wrong, and real log lines flagged as injection are reported as false positives.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from aria.config import GuardrailConfig
from aria.data.loghub import LOGHUB_DIRS, format_raw_line, iter_structured_csv
from aria.evidence import EvidenceStore
from aria.parsing.parser import parse_lines

QUARANTINED = "<quarantined>"
SALT = b"aria-eval-parsing"


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


def system_accuracy(directory: Path, system: str) -> dict[str, Any] | None:
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
    return {
        "lines": len(records),
        "events": len(set(truth)),
        "templates": len({p for p in predicted if p != QUARANTINED}),
        "grouping_accuracy": round(grouping_accuracy(predicted, truth), 4),
        "flagged_as_injection": len(out.quarantined),
    }


def summarize(loghub_dir: Path) -> dict[str, Any]:
    systems: dict[str, dict[str, Any]] = {}
    for name, system in sorted(LOGHUB_DIRS.items(), key=lambda kv: kv[1]):
        result = system_accuracy(loghub_dir / name, system)
        if result is not None:
            systems[system] = result
    lines = sum(r["lines"] for r in systems.values())
    weighted = sum(r["grouping_accuracy"] * r["lines"] for r in systems.values())
    return {
        "systems": systems,
        "n_systems": len(systems),
        "lines": lines,
        "mean_grouping_accuracy": round(
            sum(r["grouping_accuracy"] for r in systems.values()) / max(1, len(systems)), 4
        ),
        "line_weighted_grouping_accuracy": round(weighted / max(1, lines), 4),
        "real_lines_flagged_as_injection": sum(r["flagged_as_injection"] for r in systems.values()),
    }
