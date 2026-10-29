"""Declarative severity rules (``config/severity_rules.yaml``) and their evaluation.

Rules are data, not code: a condition tree over named features, evaluated without ``eval``.
Every rule that fires produces a ``RuleHit`` that says which values crossed which thresholds,
so a decision can be audited line by line.
"""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from aria.contracts.base import SEVERITY_ORDER, Severity
from aria.contracts.inputs import AlertSignal
from aria.contracts.parsing import WindowFeatures
from aria.contracts.severity import RuleHit
from aria.parsing.catalog import load_lexicon

FeatureSpace = dict[str, float]
LEVELS = ("DEBUG", "INFO", "WARN", "ERROR", "FATAL", "UNKNOWN")
_NUMERIC_FIELDS = tuple(
    name
    for name, info in WindowFeatures.model_fields.items()
    if info.annotation in (int, float, "int", "float")
)
_OPS: dict[str, Callable[[float, float], bool]] = {
    ">=": operator.ge,
    ">": operator.gt,
    "<=": operator.le,
    "<": operator.lt,
    "==": operator.eq,
    "!=": operator.ne,
}
_CRITICAL_ALERT = {"critical", "crit", "page", "sev1", "p1", "emergency", "fatal"}
_WARNING_ALERT = {"warning", "warn", "major", "high", "sev2", "p2", "error"}


def feature_space(features: WindowFeatures, alerts: Sequence[AlertSignal] = ()) -> FeatureSpace:
    """Flatten window features and alerts into the names rules and the model read."""
    values: FeatureSpace = {name: float(getattr(features, name)) for name in _NUMERIC_FIELDS}
    for level in LEVELS:
        values[f"level_counts.{level}"] = float(features.level_counts.get(level, 0))
    for category in load_lexicon():
        values[f"keyword_hits.{category}"] = float(features.keyword_hits.get(category, 0))
    values["n_critical_components"] = float(len(features.critical_components))
    firing = [a for a in alerts if a.status == "firing"]
    labels = [(a.labels.get("severity") or a.labels.get("priority") or "").lower() for a in firing]
    values["alerts.firing"] = float(len(firing))
    values["alerts.critical"] = float(sum(1 for label in labels if label in _CRITICAL_ALERT))
    values["alerts.warning"] = float(sum(1 for label in labels if label in _WARNING_ALERT))
    return values


@lru_cache(maxsize=1)
def known_features() -> frozenset[str]:
    return frozenset(feature_space(WindowFeatures.model_construct(**_zero_features())))


def _zero_features() -> dict[str, Any]:
    return {
        name: 0 if info.annotation in (int, "int") else 0.0
        for name, info in WindowFeatures.model_fields.items()
        if name in _NUMERIC_FIELDS
    } | {"level_counts": {}, "keyword_hits": {}, "components": [], "critical_components": []}


# --- condition trees ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Condition:
    feature: str
    op: str
    value: float

    def holds(self, values: Mapping[str, float]) -> bool:
        return _OPS[self.op](values.get(self.feature, 0.0), self.value)

    def describe(self, values: Mapping[str, float]) -> str:
        observed = values.get(self.feature, 0.0)
        shown = int(observed) if float(observed).is_integer() else round(observed, 3)
        threshold = int(self.value) if float(self.value).is_integer() else self.value
        return f"{self.feature}={shown} {self.op} {threshold}"


@dataclass(frozen=True)
class Group:
    mode: Literal["all", "any"]
    children: tuple[Condition | Group, ...]

    def holds(self, values: Mapping[str, float]) -> bool:
        results = (child.holds(values) for child in self.children)
        return all(results) if self.mode == "all" else any(results)

    def describe(self, values: Mapping[str, float]) -> str:
        parts = [c.describe(values) for c in self.children if self.mode == "all" or c.holds(values)]
        return " and ".join(parts) if self.mode == "all" else " or ".join(parts)


Node = Condition | Group


def parse_condition(raw: Mapping[str, Any], *, rule_id: str) -> Node:
    if "all" in raw or "any" in raw:
        mode: Literal["all", "any"] = "all" if "all" in raw else "any"
        children = raw[mode]
        if not isinstance(children, list) or not children:
            msg = f"rule {rule_id}: '{mode}' needs a non-empty list"
            raise ValueError(msg)
        return Group(mode, tuple(parse_condition(child, rule_id=rule_id) for child in children))
    feature, op, value = raw.get("feature"), raw.get("op"), raw.get("value")
    if feature not in known_features():
        msg = f"rule {rule_id}: unknown feature {feature!r}"
        raise ValueError(msg)
    if op not in _OPS:
        msg = f"rule {rule_id}: unknown operator {op!r}"
        raise ValueError(msg)
    if not isinstance(value, int | float):
        msg = f"rule {rule_id}: value must be a number"
        raise ValueError(msg)
    return Condition(str(feature), str(op), float(value))


# --- rules -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    effect: Literal["score", "floor"]
    severity: Severity
    weight: float
    when: Node


@dataclass
class RuleEvaluation:
    hits: list[RuleHit]
    scores: dict[Severity, float]
    rule_severity: Severity
    floor: Severity | None
    probabilities: dict[Severity, float]
    values: FeatureSpace = field(default_factory=dict)

    @property
    def floor_rules(self) -> list[RuleHit]:
        return [hit for hit in self.hits if hit.effect == "floor"]


DEFAULT_ACTIVATION = {Severity.SEV1: 2.5, Severity.SEV2: 2.0, Severity.SEV3: 1.0}


@dataclass(frozen=True)
class RuleSet:
    """Rules plus how their scores combine.

    The rule severity is the most severe class whose summed weight reaches its activation
    threshold, so one decisive SEV1 rule is not outvoted by several weaker SEV2 rules that a
    severe incident also trips. Noise (SEV4) rules can outvote SEV3-level signals only; they
    never dampen SEV1 or SEV2 evidence.
    """

    version: str
    rules: tuple[Rule, ...]
    auto_confidence: float = 0.85
    smoothing: float = 0.25
    activation: dict[Severity, float] = field(default_factory=lambda: dict(DEFAULT_ACTIVATION))

    def _rule_severity(self, scores: dict[Severity, float]) -> Severity:
        for severity in (Severity.SEV1, Severity.SEV2, Severity.SEV3):
            if scores[severity] >= self.activation.get(severity, float("inf")):
                if severity is Severity.SEV3 and scores[Severity.SEV4] > scores[Severity.SEV3]:
                    return Severity.SEV4
                return severity
        if not any(scores.values()):
            return Severity.SEV4
        return max(SEVERITY_ORDER, key=lambda s: (scores[s], -s.rank))

    def evaluate(self, values: Mapping[str, float]) -> RuleEvaluation:
        hits: list[RuleHit] = []
        scores = dict.fromkeys(SEVERITY_ORDER, 0.0)
        floor: Severity | None = None
        for rule in self.rules:
            if not rule.when.holds(values):
                continue
            hits.append(
                RuleHit(
                    rule_id=rule.id,
                    title=rule.title,
                    effect=rule.effect,
                    severity=rule.severity,
                    weight=rule.weight,
                    detail=rule.when.describe(values),
                )
            )
            if rule.effect == "score":
                scores[rule.severity] += rule.weight
            else:
                floor = rule.severity if floor is None else floor.more_severe(rule.severity)
        best = self._rule_severity(scores)
        total = sum(scores.values()) + self.smoothing * len(SEVERITY_ORDER)
        probabilities = {s: (scores[s] + self.smoothing) / total for s in SEVERITY_ORDER}
        return RuleEvaluation(hits, scores, best, floor, probabilities, dict(values))


def load_rules(path: Path) -> RuleSet:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules: list[Rule] = []
    seen: set[str] = set()
    for spec in raw.get("rules", []):
        rule_id = str(spec["id"])
        if rule_id in seen:
            msg = f"duplicate rule id {rule_id}"
            raise ValueError(msg)
        seen.add(rule_id)
        effect = spec.get("effect", "score")
        if effect not in ("score", "floor"):
            msg = f"rule {rule_id}: effect must be score or floor"
            raise ValueError(msg)
        rules.append(
            Rule(
                id=rule_id,
                title=str(spec["title"]),
                effect=effect,
                severity=Severity(spec["severity"]),
                weight=float(spec.get("weight", 1.0 if effect == "score" else 0.0)),
                when=parse_condition(spec["when"], rule_id=rule_id),
            )
        )
    gate = raw.get("gate") or {}
    activation = {Severity(k): float(v) for k, v in (raw.get("activation") or {}).items()}
    return RuleSet(
        version=str(raw.get("version", "unversioned")),
        rules=tuple(rules),
        auto_confidence=float(gate.get("auto_confidence", 0.85)),
        activation=activation or dict(DEFAULT_ACTIVATION),
    )
