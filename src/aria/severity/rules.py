"""Declarative severity rules (``config/severity_rules.yaml``) and their evaluation.

Rules are data, not code: a condition tree over named features, evaluated without ``eval``.
Every rule that fires produces a ``RuleHit`` that says which values crossed which thresholds,
so a decision can be audited line by line.

SEV1 needs two kinds of impact to agree. Each SEV1 rule names the impact dimensions it shows
(``DIMENSIONS``: an outage, at-risk data, a security exposure, how far it spreads...), as an
impact-by-urgency matrix would, and the rules call SEV1 only when the SEV1 rules that fired
name at least ``sev1_dimensions`` of them between them. A lone SEV1 signal still counts, as
SEV2. Floors are separate and unaffected.
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
# Kinds of impact a SEV1 rule can show. Severity schemes rate impact (how much, how far, what
# kind) against urgency; two dimensions agreeing is what separates SEV1 from a serious but
# contained SEV2.
DIMENSIONS = frozenset(
    {
        "availability",  # a service or host stops doing its work
        "integrity",  # data lost, corrupted or wrong (including money)
        "security",  # an attack, an exposure or data leaving
        "spread",  # many nodes, hosts or most of a fleet (blast radius)
        "criticality",  # a component the catalog marks critical
        "persistence",  # lasting, not a blip
        "alerting",  # monitoring itself rates it critical
    }
)
_CRITICAL_ALERT = {"critical", "crit", "page", "sev1", "p1", "emergency", "fatal"}
_WARNING_ALERT = {"warning", "warn", "major", "high", "sev2", "p2", "error"}


def feature_space(features: WindowFeatures, alerts: Sequence[AlertSignal] = ()) -> FeatureSpace:
    """Flatten window features and alerts into the names rules and the model read."""
    values: FeatureSpace = {name: float(getattr(features, name)) for name in _NUMERIC_FIELDS}
    for level in LEVELS:
        values[f"level_counts.{level}"] = float(features.level_counts.get(level, 0))
    for category in load_lexicon():
        values[f"keyword_hits.{category}"] = float(features.keyword_hits.get(category, 0))
        values[f"issue_keyword_hits.{category}"] = float(
            features.issue_keyword_hits.get(category, 0)
        )
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
    } | {
        "level_counts": {},
        "keyword_hits": {},
        "issue_keyword_hits": {},
        "components": [],
        "critical_components": [],
    }


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
    dimensions: frozenset[str] = frozenset()


@dataclass
class RuleEvaluation:
    hits: list[RuleHit]
    scores: dict[Severity, float]
    rule_severity: Severity
    floor: Severity | None
    probabilities: dict[Severity, float]
    values: FeatureSpace = field(default_factory=dict)
    # Impact dimensions the SEV1 rules that fired name between them.
    dimensions: frozenset[str] = frozenset()

    @property
    def floor_rules(self) -> list[RuleHit]:
        return [hit for hit in self.hits if hit.effect == "floor"]


DEFAULT_ACTIVATION = {Severity.SEV1: 2.5, Severity.SEV2: 2.0, Severity.SEV3: 1.0}
DEFAULT_SEV1_DIMENSIONS = 2


@dataclass(frozen=True)
class RuleSet:
    """Rules plus how their scores combine.

    The rule severity is the most severe class whose summed weight reaches its activation
    threshold, so one decisive SEV1 rule is not outvoted by several weaker SEV2 rules that a
    severe incident also trips. Noise (SEV4) rules can outvote SEV3-level signals only; they
    never dampen SEV1 or SEV2 evidence. SEV1 weight whose rules name fewer than
    ``sev1_dimensions`` impact dimensions between them counts towards SEV2 instead.
    """

    version: str
    rules: tuple[Rule, ...]
    auto_confidence: float = 0.85
    smoothing: float = 0.25
    activation: dict[Severity, float] = field(default_factory=lambda: dict(DEFAULT_ACTIVATION))
    sev1_dimensions: int = DEFAULT_SEV1_DIMENSIONS

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
        dimensions: set[str] = set()
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
                if rule.severity is Severity.SEV1:
                    dimensions |= rule.dimensions
            else:
                floor = rule.severity if floor is None else floor.more_severe(rule.severity)
        if scores[Severity.SEV1] and len(dimensions) < self.sev1_dimensions:
            # One kind of impact, however strong, is serious but not yet SEV1.
            scores[Severity.SEV2] += scores[Severity.SEV1]
            scores[Severity.SEV1] = 0.0
        best = self._rule_severity(scores)
        total = sum(scores.values()) + self.smoothing * len(SEVERITY_ORDER)
        probabilities = {s: (scores[s] + self.smoothing) / total for s in SEVERITY_ORDER}
        return RuleEvaluation(
            hits, scores, best, floor, probabilities, dict(values), frozenset(dimensions)
        )


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
        dimensions = frozenset(str(d) for d in spec.get("dimensions") or ())
        if unknown := sorted(dimensions - DIMENSIONS):
            msg = f"rule {rule_id}: unknown impact dimensions {unknown}"
            raise ValueError(msg)
        rules.append(
            Rule(
                id=rule_id,
                title=str(spec["title"]),
                effect=effect,
                severity=Severity(spec["severity"]),
                weight=float(spec.get("weight", 1.0 if effect == "score" else 0.0)),
                when=parse_condition(spec["when"], rule_id=rule_id),
                dimensions=dimensions,
            )
        )
    gate = raw.get("gate") or {}
    activation = {Severity(k): float(v) for k, v in (raw.get("activation") or {}).items()}
    activation = activation or dict(DEFAULT_ACTIVATION)
    sev1_dimensions = int(raw.get("sev1_dimensions", DEFAULT_SEV1_DIMENSIONS))
    sev1_activation = activation.get(Severity.SEV1, float("inf"))
    for rule in rules:
        decisive = rule.effect == "score" and rule.severity is Severity.SEV1
        if decisive and rule.weight >= sev1_activation and len(rule.dimensions) < sev1_dimensions:
            msg = (
                f"rule {rule.id}: a rule that decides SEV1 on its own must name at least "
                f"{sev1_dimensions} impact dimensions ({', '.join(sorted(DIMENSIONS))})"
            )
            raise ValueError(msg)
    return RuleSet(
        version=str(raw.get("version", "unversioned")),
        rules=tuple(rules),
        auto_confidence=float(gate.get("auto_confidence", 0.85)),
        activation=activation,
        sev1_dimensions=sev1_dimensions,
    )
