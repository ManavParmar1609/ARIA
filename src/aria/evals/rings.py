"""How ARIA does on systems, failure modes and sources it has never seen.

ARIA's ordinary test (ring A) uses fresh windows of the same systems, failure modes and pools of
real lines the model was trained on: it catches regressions, but it cannot say how ARIA does on a
new system. This module adds ring B, the honest estimate for that:

* **Leave one system out.** For each system, the model, its regularisation (chosen by
  cross-validation that holds out whole systems), its temperature and its conformal threshold are
  fitted again on the other systems only, then the policy scores that system's test windows.
* **Leave one failure mode out.** The same, holding out one kind of incident at a time, so a
  failure mode never seen in training is scored like a new kind of outage.

Every window is scored exactly once, by a model that never saw its group, so the pooled results
estimate how ARIA does on something new. The rules and their floors are not refitted: they are
fixed by hand and apply everywhere, which is the point of them.

Ring C, real data nobody tuned on, lives in the real-data suites; :func:`model_without` gives
them a model trained without their system.

Headline: the severe-miss rate (true SEV1 or SEV2 rated SEV3 or SEV4) with an exact one-sided
upper bound, because a handful of severe windows supports a weaker claim than its point estimate.
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from aria.contracts.parsing import WindowFeatures
from aria.data.scenarios import Scenario, ScenarioBuilder
from aria.evals import metrics as m
from aria.evals import stats as st
from aria.evals.severity import SeverityCase, score
from aria.severity.engine import SeverityEngine
from aria.severity.model import LinearModel
from aria.severity.rules import RuleSet
from aria.severity.training import LabelledWindow, SplitSeeds, build_split, fit_log_model

SEVERITIES = ("SEV1", "SEV2", "SEV3", "SEV4")


@dataclass
class TrainingWindows:
    """The labelled windows of the three fitting splits, parsed once and reused by every fold."""

    train: list[LabelledWindow]
    temperature: list[LabelledWindow]
    conformal: list[LabelledWindow]

    def keep(self, keep: Callable[[LabelledWindow], bool]) -> TrainingWindows:
        return TrainingWindows(
            [w for w in self.train if keep(w)],
            [w for w in self.temperature if keep(w)],
            [w for w in self.conformal if keep(w)],
        )


def training_windows(
    builder: ScenarioBuilder,
    rules: RuleSet,
    *,
    seeds: SplitSeeds | None = None,
    per_mode: int,
    quiet_per_system: int,
    workers: int = 1,
) -> TrainingWindows:
    seeds = seeds or SplitSeeds()
    sizes = {"per_mode": per_mode, "quiet_per_system": quiet_per_system, "workers": workers}
    return TrainingWindows(
        build_split(builder, rules, seeds.train, **sizes),
        build_split(builder, rules, seeds.temperature, **sizes),
        build_split(builder, rules, seeds.conformal, **sizes),
    )


def model_without(
    windows: TrainingWindows,
    keep: Callable[[LabelledWindow], bool],
    *,
    alpha: float,
    rules_version: str,
) -> LinearModel | None:
    """The production fitting procedure on the windows ``keep`` accepts; None when too few
    classes remain to fit one."""
    kept = windows.keep(keep)
    if len({str(w.severity) for w in kept.train}) < 2 or not kept.temperature or not kept.conformal:
        return None
    model, _ = fit_log_model(
        kept.train, kept.temperature, kept.conformal, alpha=alpha, rules_version=rules_version
    )
    return model


def mode_of(system: str, failure_mode: str) -> str:
    return f"{system}.{failure_mode}"


@dataclass
class HeldOut:
    """One window scored by a model that never saw its group."""

    group: str
    case: SeverityCase
    novelty: str = "SEV4"


@dataclass
class Ring:
    name: str
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    cases: list[HeldOut] = field(default_factory=list)


def hold_out(
    name: str,
    scenarios: Sequence[Scenario],
    features: Sequence[WindowFeatures],
    windows: TrainingWindows,
    rules: RuleSet,
    *,
    alpha: float,
    scenario_group: Callable[[Scenario], str | None],
    window_group: Callable[[LabelledWindow], str],
) -> Ring:
    """Score each group's test windows with a model fitted without that group.

    ``scenario_group`` returns None for test windows that belong to no held-out group (the quiet
    windows, when failure modes are held out); they are left out of this ring.
    """
    ring = Ring(name)
    by_group: dict[str, list[int]] = defaultdict(list)
    for i, scenario in enumerate(scenarios):
        group = scenario_group(scenario)
        if group is not None:
            by_group[group].append(i)
    for group in sorted(by_group):

        def outside(w: LabelledWindow, held: str = group) -> bool:
            return window_group(w) != held

        model = model_without(windows, outside, alpha=alpha, rules_version=rules.version)
        idx = by_group[group]
        engine = SeverityEngine(rules, model, alpha=alpha)
        cases = score(engine, [scenarios[i] for i in idx], [features[i] for i in idx])
        ring.cases += [HeldOut(group, case) for case in cases]
        ring.groups[group] = {
            "fitted_without": True,
            "model": model.version if model else "rules only (too few classes left)",
            "c": model.metadata.get("c") if model else None,
            "n_train": sum(1 for w in windows.train if window_group(w) != group),
        }
    return ring


# --- the novelty-only baseline ----------------------------------------------------------------


def novelty(values: dict[str, float]) -> float:
    """The share of a window's templates never seen in its system's routine history."""
    return float(values.get("novel_templates", 0.0)) / max(
        1.0, float(values.get("n_templates", 0.0))
    )


def fit_novelty_cuts(windows: Sequence[LabelledWindow], grid: int = 16) -> tuple[float, ...]:
    """Three cut points on novelty (SEV1 at or above the first, then SEV2, SEV3; else SEV4),
    chosen to maximise macro-F1 on the training windows.

    The baseline any learned feature must beat on unseen systems: a new system shows many new
    templates, so "how much is new" alone predicts more than it seems (Landauer et al., 2024).
    """
    scores = np.array([novelty(w.values) for w in windows])
    truth = [str(w.severity) for w in windows]
    candidates = sorted(set(np.quantile(scores, np.linspace(0.05, 0.95, grid)).round(4)))
    best: tuple[float, ...] = (1.1, 1.1, 1.1)
    best_f1 = -1.0
    for a, b, c in itertools.combinations(sorted(candidates, reverse=True), 3):
        pred = [_novelty_level(s, (a, b, c)) for s in scores]
        f1 = m.macro_f1(truth, pred)
        if f1 > best_f1:
            best, best_f1 = (a, b, c), f1
    return best


def _novelty_level(score: float, cuts: tuple[float, ...]) -> str:
    for level, cut in zip(SEVERITIES, cuts, strict=False):
        if score >= cut:
            return level
    return "SEV4"


def novelty_level(features: WindowFeatures, cuts: tuple[float, ...]) -> str:
    return _novelty_level(
        features.novel_templates / max(1, features.n_templates),
        cuts,
    )


# --- summaries -------------------------------------------------------------------------------


def _rate(hits: int, n: int) -> dict[str, Any]:
    low, high = st.wilson(hits, n)
    return {
        "hits": hits,
        "n": n,
        "rate": round(hits / n, 4) if n else None,
        "ci95": [round(low, 4), round(high, 4)],
    }


def _severe(truth: Sequence[str], pred: Sequence[str]) -> dict[str, Any]:
    misses, severe = st.severe_misses(truth, pred)
    return {
        "misses": misses,
        "severe": severe,
        "rate": round(misses / severe, 4) if severe else None,
        # "At most this, with 95% confidence": the honest headline for a small severe slice.
        "upper95": round(st.upper_bound(misses, severe), 4),
    }


def summarize_ring(ring: Ring, *, alpha: float) -> dict[str, Any]:
    cases = [h.case for h in ring.cases]
    groups = [h.group for h in ring.cases]
    truth = [c.truth for c in cases]
    aria = [c.aria for c in cases]
    rules = [c.rules for c in cases]
    model = [c.model for c in cases]
    novelty_pred = [h.novelty for h in ring.cases]
    if not cases:
        return {"n": 0}
    over, n = st.over_triage(truth, aria)
    deferred = sum(1 for c in cases if c.needs_review)
    covered = sum(1 for c in cases if c.truth in c.prediction_set)
    accuracy = m.accuracy(truth, aria)
    f1_low, f1_high = st.cluster_bootstrap(m.macro_f1, truth, aria, groups)
    comparisons = {
        "rules_only": st.compare(truth, aria, rules),
        "model_only": st.compare(truth, aria, model),
        "novelty_only": st.compare(truth, aria, novelty_pred),
    }
    adjusted = st.holm({name: float(c["p_correct"]) for name, c in comparisons.items()})
    for name, c in comparisons.items():
        c["p_correct_holm"] = round(adjusted[name], 4)
    per_group: dict[str, Any] = {}
    for group in sorted(set(groups)):
        idx = [i for i, g in enumerate(groups) if g == group]
        t = [truth[i] for i in idx]
        p = [aria[i] for i in idx]
        per_group[group] = {
            **ring.groups.get(group, {}),
            "n": len(idx),
            "accuracy": round(m.accuracy(t, p), 4),
            "severe": _severe(t, p),
            "deferred": round(sum(1 for i in idx if cases[i].needs_review) / len(idx), 4),
            "covered": round(
                sum(1 for i in idx if cases[i].truth in cases[i].prediction_set) / len(idx), 4
            ),
            "labels": dict(sorted(Counter(t).items())),
        }
    accuracies = [g["accuracy"] for g in per_group.values()]
    worst = min(per_group, key=lambda g: per_group[g]["accuracy"])
    by_class_coverage = {
        cls: _rate(
            sum(1 for c in cases if c.truth == cls and cls in c.prediction_set),
            sum(1 for c in cases if c.truth == cls),
        )
        for cls in SEVERITIES
        if any(c.truth == cls for c in cases)
    }
    return {
        "name": ring.name,
        "n": len(cases),
        "groups": len(per_group),
        "labels": dict(sorted(Counter(truth).items())),
        "severe": _severe(truth, aria),
        "severe_sev1": _severe(
            [t for t in truth if t == "SEV1"],
            [a for t, a in zip(truth, aria, strict=True) if t == "SEV1"],
        ),
        "over_triage": _rate(over, n),
        "deferred": _rate(deferred, n),
        "accuracy": {**_rate(sum(t == a for t, a in zip(truth, aria, strict=True)), n)},
        "macro_f1": {
            "value": round(m.macro_f1(truth, aria), 4),
            "ci95_by_group": [round(f1_low, 4), round(f1_high, 4)],
        },
        "macro_mae": round(st.macro_mae(truth, aria), 4),
        "nll": round(st.nll([c.probabilities for c in cases], truth), 4),
        "smooth_ece": round(
            st.smooth_ece(
                [max(c.probabilities.values()) for c in cases],
                [c.model == c.truth for c in cases],
            ),
            4,
        ),
        "coverage": {
            "target": round(1 - alpha, 3),
            "all": _rate(covered, n),
            "by_class": by_class_coverage,
            "mean_set_size": round(sum(len(c.prediction_set) for c in cases) / n, 3),
        },
        "methods": {
            "aria_policy": {"accuracy": round(accuracy, 4), "severe": _severe(truth, aria)},
            "rules_only": {
                "accuracy": round(m.accuracy(truth, rules), 4),
                "severe": _severe(truth, rules),
            },
            "model_only": {
                "accuracy": round(m.accuracy(truth, model), 4),
                "severe": _severe(truth, model),
            },
            "novelty_only": {
                "accuracy": round(m.accuracy(truth, novelty_pred), 4),
                "severe": _severe(truth, novelty_pred),
            },
        },
        "against": comparisons,
        "spread": {
            "median_accuracy": round(float(np.median(accuracies)), 4),
            "worst_group": worst,
            "worst_accuracy": per_group[worst]["accuracy"],
            "groups_with_a_severe_miss": sorted(
                g for g, v in per_group.items() if v["severe"]["misses"]
            ),
        },
        "by_group": per_group,
    }


def evaluate(
    builder: ScenarioBuilder,
    rules: RuleSet,
    test: Sequence[Scenario],
    features: Sequence[WindowFeatures],
    *,
    alpha: float,
    per_mode: int,
    quiet_per_system: int,
    workers: int = 1,
    windows: TrainingWindows | None = None,
) -> dict[str, Any]:
    """Ring B: leave one system out, and leave one failure mode out, on the test seeds."""
    windows = windows or training_windows(
        builder, rules, per_mode=per_mode, quiet_per_system=quiet_per_system, workers=workers
    )
    cuts = fit_novelty_cuts(windows.train)
    by_system = hold_out(
        "leave_one_system_out",
        test,
        features,
        windows,
        rules,
        alpha=alpha,
        scenario_group=lambda s: s.system,
        window_group=lambda w: w.system,
    )
    benign = {k for k, mode in builder.pools.modes.items() if mode.benign}
    by_mode = hold_out(
        "leave_one_failure_mode_out",
        test,
        features,
        windows,
        rules,
        alpha=alpha,
        # Quiet windows are no failure mode; benign noise modes are held out like any other.
        scenario_group=lambda s: (
            None if s.failure_mode == "none" else mode_of(s.system, s.failure_mode)
        ),
        window_group=lambda w: mode_of(w.system, w.failure_mode),
    )
    lookup = {s.id: features[i] for i, s in enumerate(test)}
    for ring in (by_system, by_mode):
        for held in ring.cases:
            held.novelty = novelty_level(lookup[held.case.id], cuts)
    return {
        "seeds": {
            "test": list(SplitSeeds().test),
            "fitting": "train, temperature and conformal seeds",
        },
        "novelty_cuts": [round(c, 4) for c in cuts],
        "benign_modes": sorted(benign),
        "leave_one_system_out": summarize_ring(by_system, alpha=alpha),
        "leave_one_failure_mode_out": summarize_ring(by_mode, alpha=alpha),
    }


__all__ = [
    "HeldOut",
    "Ring",
    "TrainingWindows",
    "evaluate",
    "fit_novelty_cuts",
    "hold_out",
    "model_without",
    "novelty_level",
    "summarize_ring",
    "training_windows",
]
