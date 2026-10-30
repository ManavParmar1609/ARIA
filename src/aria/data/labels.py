"""Ground-truth severity labels for log windows.

Labels come from dataset annotations (BGL sysadmin alert tags) through a documented rubric in
``config/labeling/bgl_alert_impact.yaml``. The rubric reads tags and their spread; ARIA's runtime
rules read only log text, so the benchmark does not grade the rules against themselves.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from aria.contracts.base import Severity

ImpactClass = Literal["critical", "major", "minor"]
RUBRIC_PATH = Path("config/labeling/bgl_alert_impact.yaml")


@dataclass(frozen=True)
class AlertRubric:
    tag_class: dict[str, ImpactClass]
    default_class: ImpactClass
    rules: list[tuple[Severity, list[dict[str, Any]]]]
    descriptions: dict[str, str] = field(default_factory=dict)

    def impact(self, tag: str) -> ImpactClass:
        return self.tag_class.get(tag, self.default_class)


@lru_cache(maxsize=4)
def load_rubric(path: Path = RUBRIC_PATH) -> AlertRubric:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    tag_class: dict[str, ImpactClass] = {}
    descriptions: dict[str, str] = {}
    for cls, tags in raw["classes"].items():
        for tag, description in tags.items():
            tag_class[tag] = cls
            descriptions[tag] = description
    rules = [(Severity(rule["severity"]), list(rule["any_of"])) for rule in raw["window_rules"]]
    return AlertRubric(tag_class, raw.get("default_class", "major"), rules, descriptions)


@dataclass
class WindowTagStats:
    alerts: Counter[ImpactClass] = field(default_factory=Counter)
    nodes: dict[ImpactClass, set[str]] = field(
        default_factory=lambda: {"critical": set(), "major": set(), "minor": set()}
    )
    tags: Counter[str] = field(default_factory=Counter)

    def as_conditions(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for cls in ("critical", "major", "minor"):
            out[f"{cls}_alerts"] = self.alerts[cls]
            out[f"{cls}_nodes"] = len(self.nodes[cls])
        return out


def tag_stats(tagged: Iterable[tuple[str, str | None]], rubric: AlertRubric) -> WindowTagStats:
    """Aggregate (tag, node) pairs; a node with no name still counts as one alert source."""
    stats = WindowTagStats()
    for tag, node in tagged:
        cls = rubric.impact(tag)
        stats.alerts[cls] += 1
        stats.tags[tag] += 1
        stats.nodes[cls].add(node or f"unknown-{tag}")
    return stats


def _condition_holds(condition: dict[str, Any], values: dict[str, int]) -> bool:
    for key, threshold in condition.items():
        if key == "always":
            if not threshold:
                return False
            continue
        metric = key.removesuffix("_at_least")
        if values.get(metric, 0) < int(threshold):
            return False
    return True


def label_window(stats: WindowTagStats, rubric: AlertRubric) -> tuple[Severity, dict[str, Any]]:
    values = stats.as_conditions()
    for severity, any_of in rubric.rules:
        for condition in any_of:
            if _condition_holds(condition, values):
                return severity, {"rule": condition, "counts": values, "tags": dict(stats.tags)}
    return Severity.SEV4, {"rule": None, "counts": values, "tags": dict(stats.tags)}
