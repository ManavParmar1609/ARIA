"""Severity evaluation on the held-out test seeds, against simple baselines.

Every window is parsed by the production parser and scored by the production engine, exactly as
a run would, with no LLM: the policy's offline path (auto-decide when the calibrated model is
confident and the conformal set has one class, otherwise the most severe class in the set). That
is the conservative floor of ARIA's behaviour; an LLM adjudicator can only choose within the
same set.

Baselines: the majority class; keyword matching alone; rules alone; the calibrated model's top
class without the policy; and TF-IDF over raw log text with logistic regression, trained on the
training seeds.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from aria.contracts.base import Severity
from aria.contracts.parsing import WindowFeatures
from aria.data.scenarios import Scenario, ScenarioBuilder
from aria.evals import metrics as m
from aria.evidence import EvidenceStore
from aria.severity.engine import SeverityEngine
from aria.severity.policy import decide
from aria.severity.training import SplitSeeds, features_for, known_templates

REPORT_PATH = Path("models/severity_log.report.json")
# The keyword baseline: the most severe category with at least KEYWORD_MIN_LINES matching lines.
KEYWORD_SEVERITY = (
    (Severity.SEV1, ("crash", "data_risk")),
    (Severity.SEV2, ("unavailable", "resource")),
    (Severity.SEV3, ("security", "hardware", "storage", "network")),
)
KEYWORD_MIN_LINES = 3


@dataclass
class SeverityCase:
    id: str
    system: str
    failure_mode: str
    truth: str
    label_source: str
    keyword: str
    rules: str
    model: str
    model_floored: str
    aria: str
    decided_by: str
    needs_review: bool
    probabilities: dict[str, float]
    prediction_set: list[str]
    raw_set: list[str]


def held_out(
    builder: ScenarioBuilder, *, seeds: Sequence[int], per_mode: int, quiet_per_system: int
) -> list[Scenario]:
    return [
        scenario
        for seed in seeds
        for scenario in builder.suite(
            seed=seed, per_mode=per_mode, quiet_per_system=quiet_per_system
        )
    ]


def featurize(
    builder: ScenarioBuilder, scenarios: Sequence[Scenario], *, workers: int = 1
) -> list[WindowFeatures]:
    """Production-parser features, with the same 'known templates' history training used."""
    known = {s.system: known_templates(builder, s.system) for s in scenarios}
    args = (
        [s.system for s in scenarios],
        [s.lines for s in scenarios],
        [known[s.system] for s in scenarios],
    )
    if workers > 1 and len(scenarios) > 2 * workers:
        with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
            return list(pool.map(features_for, *args, chunksize=4))
    return [features_for(*item) for item in zip(*args, strict=True)]


def keyword_severity(features: WindowFeatures) -> str:
    """Severity from keyword categories alone, the way a keyword-frequency triage rule works."""
    for severity, categories in KEYWORD_SEVERITY:
        if any(features.keyword_hits.get(c, 0) >= KEYWORD_MIN_LINES for c in categories):
            return str(severity)
    return str(Severity.SEV4)


def score(
    engine: SeverityEngine, scenarios: Sequence[Scenario], features: Sequence[WindowFeatures]
) -> list[SeverityCase]:
    cases = []
    for scenario, feats in zip(scenarios, features, strict=True):
        pre = engine.preliminary(feats, evidence=EvidenceStore())
        decision = decide(pre, gate=engine.gate, llm_unavailable_reason="offline evaluation")
        probabilities = {str(k): round(v, 6) for k, v in pre.probabilities.items()}
        model_top = max(probabilities, key=probabilities.__getitem__)
        cases.append(
            SeverityCase(
                id=scenario.id,
                system=scenario.system,
                failure_mode=scenario.failure_mode,
                truth=str(scenario.severity),
                label_source=scenario.label_source,
                keyword=keyword_severity(feats),
                rules=str(pre.rule_severity),
                model=model_top,
                model_floored=str(pre.top),
                aria=str(decision.severity),
                decided_by=decision.decided_by,
                needs_review=decision.needs_review,
                probabilities=probabilities,
                prediction_set=[str(s) for s in pre.prediction_set],
                raw_set=[str(s) for s in pre.raw_set],
            )
        )
    return cases


def majority_label(report_path: Path = REPORT_PATH) -> str:
    """The most common training label (from the training report), for the majority baseline."""
    if report_path.exists():
        labels = json.loads(report_path.read_text())["labels"]["train"]
        return str(max(labels, key=labels.__getitem__))
    return str(Severity.SEV3)


# Raw lines from these systems open with the sysadmin alert tag ("-" or e.g. "KERNDTLB").
TAGGED_SYSTEMS = frozenset({"bgl", "thunderbird"})


def baseline_text(scenario: Scenario) -> str:
    """The window's raw lines without the alert tag BGL and Thunderbird lines open with.

    The BGL labels come from that tag, so a baseline that read it would see the answer.
    ARIA's features and the evidence it shows models never read the tag either.
    """
    lines = scenario.lines
    if scenario.system in TAGGED_SYSTEMS:
        lines = [line.split(" ", 1)[1] if " " in line else "" for line in lines]
    return "\n".join(lines)


def tfidf_baseline(
    builder: ScenarioBuilder,
    test: Sequence[Scenario],
    *,
    per_mode: int,
    quiet_per_system: int,
    seeds: Sequence[int] = SplitSeeds().train,
) -> list[str]:
    """Bag-of-words over raw lines: what a text classifier learns without ARIA's parsing."""
    from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: PLC0415 - heavy import
    from sklearn.linear_model import LogisticRegression  # noqa: PLC0415

    train = held_out(builder, seeds=seeds, per_mode=per_mode, quiet_per_system=quiet_per_system)
    vectorizer = TfidfVectorizer(
        max_features=30_000,
        ngram_range=(1, 2),
        sublinear_tf=True,
        token_pattern=r"[A-Za-z_]{3,}",  # noqa: S106 - a regex, not a password
    )
    x_train = vectorizer.fit_transform([baseline_text(s) for s in train])
    classifier = LogisticRegression(max_iter=3_000, class_weight="balanced", C=3.0)
    classifier.fit(x_train, [str(s.severity) for s in train])
    predictions = classifier.predict(vectorizer.transform([baseline_text(s) for s in test]))
    return [str(p) for p in predictions]


def summarize(
    cases: Sequence[SeverityCase],
    *,
    alpha: float,
    majority: str,
    tfidf: Sequence[str] | None = None,
) -> dict[str, Any]:
    truth = [c.truth for c in cases]
    methods: dict[str, Sequence[str]] = {
        "aria_policy": [c.aria for c in cases],
        "model_with_floors": [c.model_floored for c in cases],
        "model_only": [c.model for c in cases],
        "rules_only": [c.rules for c in cases],
        "keyword": [c.keyword for c in cases],
        "majority_class": [majority] * len(cases),
    }
    if tfidf is not None:
        methods["tfidf_logreg"] = list(tfidf)
    auto = [c for c in cases if not c.needs_review]
    flagged = [c for c in cases if c.needs_review]
    by_system: dict[str, dict[str, Any]] = {}
    for system in sorted({c.system for c in cases}):
        subset = [c for c in cases if c.system == system]
        by_system[system] = {
            "n": len(subset),
            "accuracy": round(m.accuracy([c.truth for c in subset], [c.aria for c in subset]), 4),
            "severe_under_triage": round(
                m.severe_under_triage([c.truth for c in subset], [c.aria for c in subset]), 4
            ),
            "label_source": Counter(c.label_source for c in subset).most_common(1)[0][0],
        }
    return {
        "n": len(cases),
        "label_distribution": dict(sorted(Counter(truth).items())),
        "methods": {name: m.classification_report(truth, pred) for name, pred in methods.items()},
        "calibration": {
            "ece": round(m.expected_calibration_error([c.probabilities for c in cases], truth), 4),
            "brier": round(m.brier([c.probabilities for c in cases], truth), 4),
        },
        # The calibrated model abstaining on its least confident windows.
        "risk_coverage": m.risk_coverage(
            [max(c.probabilities.values()) for c in cases],
            [c.model == c.truth for c in cases],
        ),
        "conformal": {
            "alpha": alpha,
            "target_coverage": round(1 - alpha, 3),
            "coverage_raw": round(m.set_coverage([c.raw_set for c in cases], truth), 4),
            "coverage_with_floors": round(
                m.set_coverage([c.prediction_set for c in cases], truth), 4
            ),
            "mean_set_size": round(
                sum(len(c.prediction_set) for c in cases) / max(1, len(cases)), 3
            ),
        },
        "automation": {
            "auto_decided": round(len(auto) / max(1, len(cases)), 4),
            "accuracy_when_auto": round(
                m.accuracy([c.truth for c in auto], [c.aria for c in auto]), 4
            ),
            "accuracy_when_flagged": round(
                m.accuracy([c.truth for c in flagged], [c.aria for c in flagged]), 4
            ),
            "decided_by": dict(Counter(c.decided_by for c in cases)),
        },
        "by_system": by_system,
    }
