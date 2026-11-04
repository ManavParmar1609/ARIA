"""The severity agent's core: rules, then the calibrated model, then the decision policy."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from aria.config import SeverityConfig
from aria.contracts.base import SEVERITY_ORDER, EvidenceKind, Severity
from aria.contracts.inputs import AlertSignal
from aria.contracts.parsing import WindowFeatures
from aria.contracts.severity import RuleHit, SeverityAssessment
from aria.evidence import EvidenceStore
from aria.llm.budget import BudgetGuard
from aria.llm.router import LLMRouter
from aria.observability.logging import get_logger
from aria.severity.adjudicator import Adjudication, ReviewedExample, adjudicate
from aria.severity.conformal import FAMILIAR
from aria.severity.features import log_feature_row
from aria.severity.history import HistoryContext, SystemHistory
from aria.severity.model import LinearModel, live_model_path
from aria.severity.policy import DismissedNote, Preliminary, coverage_words, decide
from aria.severity.rules import HISTORY_FEATURES, RuleSet, feature_space, load_rules

log = get_logger(__name__)
RULES_ONLY_MIN_P = 0.2
# How far (in training standard deviations) a window's features may sit from the training mean
# before the model is not used. No training or held-out window reaches it; a handful of lines or
# an alert with no logs is far past it.
MODEL_RANGE_Z = 6.0
# How far past the range of its training data (as a share of that range) a feature may go before
# the model is not used. A window far longer than any it learned from, or with far more new
# patterns, sits within six deviations yet beyond anything the model saw: there it extrapolates
# (it rated healthy OpenStack runs SEV1), so the rules decide and a person reviews. Chosen on the
# validation seeds only.
MODEL_RANGE_TOLERANCE = 0.25


@dataclass
class SeverityResult:
    assessment: SeverityAssessment
    preliminary: Preliminary
    adjudication: Adjudication | None


class SeverityEngine:
    def __init__(
        self,
        rules: RuleSet,
        model: LinearModel | None,
        *,
        alpha: float,
        model_path: Path | None = None,
        trained_version: str | None = None,
        history: SystemHistory | None = None,
    ) -> None:
        self.rules = rules
        self.default_alpha = alpha
        self.model_path = model_path
        # The version this release trained: a recalibration of any other is stale.
        self.trained_version = trained_version
        # The deployment's own runs and reviews (the runner sets it); None reads nothing, as
        # evaluations do.
        self.history = history
        self._model_mtime = _mtime(model_path)
        # Told (previous version, new version) whenever a running engine swaps its model, so the
        # swap goes on the decision record (aria.services wires it up).
        self.on_swap: Callable[[str | None, str], None] | None = None
        self._set_model(model)

    def _set_model(self, model: LinearModel | None) -> None:
        if model is not None and model.classes != [str(s) for s in SEVERITY_ORDER]:
            msg = f"severity model classes {model.classes} do not match {SEVERITY_ORDER}"
            raise ValueError(msg)
        self.model = model
        self.alpha = (
            model.alpha
            if model is not None and model.conformal_q is not None
            else self.default_alpha
        )

    @classmethod
    def load(cls, config: SeverityConfig, *, models_dir: Path | None = None) -> SeverityEngine:
        """Load the rules and the model in use: the live (recalibrated) one, else the trained one.

        The engine then watches the live path, so ``refresh`` picks up the first recalibration.
        """
        rules = load_rules(config.rules_file)
        trained = Path(config.log_model_file)
        live = live_model_path(trained, models_dir) if models_dir is not None else trained
        model = LinearModel.load(trained) if trained.exists() else None
        # In a checkout the live and shipped files are one: whatever it holds (a recalibration, or
        # a model retrained in place) is the model, so there is no other release to guard against.
        version = model.trained_version if model is not None and live != trained else None
        if live != trained and live.exists():
            recalibrated = LinearModel.load(live)
            if version is None or recalibrated.trained_version == version:
                model = recalibrated
            else:  # an upgrade shipped a retrained model: the old one's recalibration is stale
                log.warning(
                    "severity.live_model_outdated", live=recalibrated.version, trained=version
                )
        if model is None:
            log.warning("severity.model_missing", path=str(trained))
        return cls(rules, model, alpha=config.alpha, model_path=live, trained_version=version)

    def refresh(self) -> bool:
        """Reload the model when its file changed (a recalibration in this or another process)."""
        mtime = _mtime(self.model_path)
        if self.model_path is None or mtime is None or mtime == self._model_mtime:
            return False
        try:
            model = LinearModel.load(self.model_path)
        except (OSError, ValueError):  # caught mid-write; the next call retries
            log.warning("severity.model_reload_failed", path=str(self.model_path))
            return False
        self._model_mtime = mtime
        if self.trained_version is not None and model.trained_version != self.trained_version:
            # Written by a process still on the previous release, mid-upgrade.
            log.warning("severity.live_model_outdated", live=model.version)
            return False
        previous = self.model.version if self.model is not None else None
        self._set_model(model)
        log.info("severity.model_reloaded", version=model.version)
        if self.on_swap is not None:
            self.on_swap(previous, model.version)
        return True

    def model_row(
        self, features: WindowFeatures, alerts: Sequence[AlertSignal] = ()
    ) -> dict[str, float]:
        """The calibrated model's input for a window: what a review hands to recalibration."""
        values = feature_space(features, alerts)
        return log_feature_row(values, self.rules.evaluate(values))

    @property
    def gate(self) -> float:
        return self.rules.auto_confidence

    def trained_on(self, system: str) -> bool:
        """Whether the model learned from this system's logs (by name, as its file records).

        Its calibration was measured on systems it trained on; on any other, including logs
        pasted as generic text, its sets miss more often (the published held-out-system results),
        so a person confirms. Model files that do not list their systems count as trained on all.
        """
        if self.model is None:
            return True
        trained = {str(s).strip().lower() for s in self.model.metadata.get("trained_systems") or []}
        return not trained or system.strip().lower() in trained

    def preliminary(
        self,
        features: WindowFeatures,
        *,
        system: str,
        alerts: Sequence[AlertSignal] = (),
        evidence: EvidenceStore,
        related: Sequence[str] = (),
        history: HistoryContext | None = None,
    ) -> Preliminary:
        self.refresh()
        values = feature_space(features, alerts, history.features if history else None)
        evaluation = self.rules.evaluate(values)
        hits: list[RuleHit] = []
        rule_ids: list[str] = []
        if history is not None and history.features:
            _history_evidence(evidence, system, features, history.features)
        for hit in evaluation.hits:
            eid = evidence.add(
                EvidenceKind.RULE,
                f"Rule {hit.rule_id} ({hit.effect} {hit.severity}): {hit.title}",
                source="severity.rules",
                detail=hit.detail,
                data={
                    "rule_id": hit.rule_id,
                    "effect": hit.effect,
                    "severity": str(hit.severity),
                    "weight": hit.weight,
                    "rules_version": self.rules.version,
                    "related": list(related)[:6],
                },
            )
            hits.append(hit.model_copy(update={"evidence_ids": [eid]}))
            rule_ids.append(eid)

        outside: list[str] = []
        novelty: list[str] = []
        extra: dict[str, Any] = {}
        alphas: dict[Severity, float] = {}
        kind = FAMILIAR
        if self.model is not None:
            x = self.model.matrix([log_feature_row(values, evaluation)])
            outside = self.model.outside_training(x[0], MODEL_RANGE_Z, MODEL_RANGE_TOLERANCE)
        if self.model is None or outside:
            probabilities = evaluation.probabilities
            raw_set = [s for s in SEVERITY_ORDER if probabilities[s] >= RULES_ONLY_MIN_P]
            set_empty = not raw_set
            raw_set = raw_set or [evaluation.rule_severity]
            version, conformal, kind = f"rules-only:{self.rules.version}", False, "rules"
            if outside:
                extra = {"outside_training": outside[:6]}
                novelty = ["outside_training"]
        else:
            calibration = self.model.calibrations.get(kind)
            probs = self.model.predict_proba(x, kind)[0]
            probabilities = {
                Severity(c): float(p) for c, p in zip(self.model.classes, probs, strict=True)
            }
            top = max(probabilities, key=lambda s: probabilities[s])
            version = self.model.version
            if calibration is not None:
                chosen = calibration.classes_in(probs, self.model.classes)
                set_empty, conformal = not chosen, True
                raw_set = [Severity(c) for c in chosen] or [Severity(str(top))]
                # An adaptive miss rate below zero means "keep every level": promise 100%.
                alphas = {Severity(c): min(max(a, 0.0), 1.0) for c, a in calibration.alphas.items()}
                extra = {
                    "calibration": kind,
                    "thresholds": {
                        c: round(calibration.threshold(c), 4) for c in self.model.classes
                    },
                    "severe_miss_risk": calibration.epsilon,
                    "guard": None if calibration.guard is None else round(calibration.guard, 4),
                }
            else:  # a model saved before per-level calibrations: one threshold for every level
                raw_set = [Severity(c) for c in self.model.prediction_sets(probs[None, :])[0]]
                conformal = self.model.conformal_q is not None
                q = self.model.conformal_q
                set_empty = q is not None and not any(float(p) >= 1.0 - q for p in probs)
                kind = "single"
            if set_empty:
                # No level is likely enough on its own: the model's most likely level and the
                # rules' level both stay possible, and the conservative policy plans for the more
                # serious of the two. (The most likely alone once rated an outage the rules
                # called SEV2 as SEV4.)
                raw_set = sorted(
                    {Severity(str(top)), evaluation.rule_severity}, key=lambda s: s.rank
                )
            novelty = self._novelty(x[0], features, raw_set, set_empty)
            if not self.trained_on(system):
                novelty.append("new_system")
            if {"unusual_mix", "new_patterns"} & set(novelty):
                # The model's probabilities are least trustworthy on a window unlike its
                # training data, so the levels the rules leave open stay possible too.
                rules_open = [
                    s for s in SEVERITY_ORDER if evaluation.probabilities[s] >= RULES_ONLY_MIN_P
                ]
                raw_set = _span({*raw_set, *rules_open, evaluation.rule_severity})
            extra |= {
                "novelty": novelty,
                "conformal_q": self.model.conformal_q,
                "temperature": round(
                    calibration.temperature if calibration is not None else self.model.temperature,
                    4,
                ),
                "top_contributions": self.model.contributions(x[0], str(top)),
            }
        shown = ", ".join(f"{s} {probabilities[s]:.2f}" for s in SEVERITY_ORDER)
        words = coverage_words(alphas or dict.fromkeys(SEVERITY_ORDER, self.alpha))
        # Without the calibrated model the numbers are rule scores; the title says so too.
        model_eid = evidence.add(
            EvidenceKind.MODEL,
            f"{'Severity' if conformal else 'Rule-score'} probabilities: {shown}",
            source="severity.model",
            detail=(
                (
                    f"No severity is likely enough for the {words} on its own; the model's most "
                    f"likely class and the rules' stay possible: {{{', '.join(raw_set)}}}."
                    if set_empty
                    else f"The {words}: {{{', '.join(raw_set)}}}"
                )
                if conformal
                else (
                    "The calibrated model was not used: this window is unlike the ones it learned "
                    f"from ({', '.join(outside[:3])}), so probabilities are normalised rule scores."
                    if outside
                    else "No calibrated model is loaded; probabilities are normalised rule scores."
                )
            ),
            data={
                "probabilities": {str(k): round(v, 6) for k, v in probabilities.items()},
                "prediction_set": [str(s) for s in raw_set],
                "set_empty": set_empty,
                "alpha": self.alpha,
                "coverage_target": round(1 - self.alpha, 4),
                "alphas": {str(k): v for k, v in alphas.items()},
                "model_version": version,
                "conformal": conformal,
                **extra,
            },
        )
        return Preliminary(
            rule_severity=evaluation.rule_severity,
            rule_scores=evaluation.scores,
            rule_hits=hits,
            floor=evaluation.floor,
            probabilities=probabilities,
            raw_set=sorted(raw_set, key=lambda s: s.rank),
            alpha=self.alpha,
            model_version=version,
            rule_evidence=rule_ids,
            model_evidence=model_eid,
            conformal=conformal,
            set_empty=set_empty,
            outside_training=outside,
            alphas=alphas,
            calibration=kind,
            novelty=novelty,
            dismissed=_dismissed_note(evidence, system, features, history),
        )

    async def _lookup(self, system: str, features: WindowFeatures) -> HistoryContext | None:
        """The system's history, read in a thread. None without a database, and when the
        database does not answer: a triage never fails for want of history."""
        if self.history is None:
            return None
        try:
            return await asyncio.to_thread(
                self.history.lookup, system, error_ratio=features.error_ratio
            )
        except Exception:  # history is a convenience: log it and rate the window without it
            log.exception("severity.history_unavailable", system=system)
            return None

    def _novelty(
        self,
        x_row: np.ndarray,
        features: WindowFeatures,
        raw_set: Sequence[Severity],
        set_empty: bool,
    ) -> list[str]:
        """Why this window should go to a person even though the model was used.

        ``unusual_mix``: its features sit further from the training windows than nearly all
        held-out windows do (a conformal p-value below the model's level). ``new_patterns``: so
        does the share of its log patterns that are new to the system. ``empty_set`` and
        ``every_level``: the set says the model cannot tell. (``new_system``, added by the
        caller: the model never trained on the window's system.)
        """
        reasons: list[str] = []
        stats = self.model.novelty if self.model is not None else None
        if stats is not None:
            if stats.p_value(self.model.standardise(x_row)) < stats.level:  # type: ignore[union-attr]
                reasons.append("unusual_mix")
            share = features.novel_templates / max(features.n_templates, 1)
            if stats.share_p_value(share) < stats.level:
                reasons.append("new_patterns")
        if set_empty:
            reasons.append("empty_set")
        elif len(set(raw_set)) == len(SEVERITY_ORDER):
            reasons.append("every_level")
        return reasons

    async def assess(
        self,
        features: WindowFeatures,
        *,
        system: str,
        evidence: EvidenceStore,
        alerts: Sequence[AlertSignal] = (),
        related: Sequence[str] = (),
        router: LLMRouter | None = None,
        budget: BudgetGuard | None = None,
        use_llm: bool = True,
        examples: Sequence[ReviewedExample] = (),
    ) -> SeverityResult:
        history = await self._lookup(system, features)
        pre = self.preliminary(
            features,
            system=system,
            alerts=alerts,
            evidence=evidence,
            related=related,
            history=history,
        )
        if pre.auto_decision(self.gate) is not None:
            return SeverityResult(decide(pre, gate=self.gate), pre, None)
        if not use_llm or router is None:
            reason = (
                "LLM use is turned off for this run"
                if not use_llm
                else "no LLM router is available"
            )
            return SeverityResult(
                decide(pre, gate=self.gate, llm_unavailable_reason=reason), pre, None
            )
        values = feature_space(features, alerts, history.features if history else None)
        result = await adjudicate(
            pre,
            system=system,
            features={k: v for k, v in values.items() if v},
            evidence=evidence.all(),
            router=router,
            budget=budget,
            examples=examples,
        )
        assessment = decide(
            pre,
            gate=self.gate,
            llm_choice=result.severity,
            llm_claims=result.claims,
            llm_unavailable_reason=result.reason,
        )
        return SeverityResult(assessment, pre, result)


def _history_evidence(
    evidence: EvidenceStore, system: str, features: WindowFeatures, found: Mapping[str, float]
) -> str:
    """The window's error ratio against the system's own baseline, as a feature item."""
    burn = found.get("error_ratio_vs_baseline", 0.0)
    return evidence.add(
        EvidenceKind.FEATURE,
        f"Errors at {burn:.1f}x this system's usual ratio",
        source="severity.history",
        detail=(
            f"error ratio {features.error_ratio:.4f} against a median of "
            f"{found.get('baseline_error_ratio', 0.0):.4f} over {system}'s last "
            f"{int(found.get('baseline_runs', 0))} finished runs (the Google SRE workbook's "
            "burn rate, with this system's usual ratio as the budget)"
        ),
        data={
            "error_ratio": features.error_ratio,
            **{k: found[k] for k in HISTORY_FEATURES if k in found},
        },
    )


def _dismissed_note(
    evidence: EvidenceStore,
    system: str,
    features: WindowFeatures,
    history: HistoryContext | None,
) -> DismissedNote | None:
    """A feedback item when most of the window's issue lines follow patterns reviewers dismissed
    on this system before. It is shown to the reviewer and scored by nothing."""
    if history is None or history.dismissed is None:
        return None
    match = history.dismissed.match(features.issue_templates, features.issue_events)
    if match is None:
        return None
    times = "once" if match.reviews == 1 else f"{match.reviews} times"
    eid = evidence.add(
        EvidenceKind.FEEDBACK,
        f"Reviewers dismissed this pattern {times} before on {system}",
        source="memory.feedback",
        detail=(
            f"{match.matched_lines} of the window's {match.issue_lines} issue lines follow log "
            f"patterns from {system} reports that reviewers discarded or lowered to SEV4 "
            f"({match.reviews} such reviews). This informs the review; it does not lower the "
            "level."
        ),
        data={
            "dismissed_reviews": match.reviews,
            "matched_lines": match.matched_lines,
            "issue_lines": match.issue_lines,
            "templates": list(match.templates),
        },
    )
    return DismissedNote(match.reviews, match.matched_lines, match.issue_lines, eid)


def _span(levels: set[Severity]) -> list[Severity]:
    """Every level between the most and the least severe of ``levels``, most severe first."""
    ranks = sorted(level.rank for level in levels)
    return [s for s in SEVERITY_ORDER if ranks[0] <= s.rank <= ranks[-1]]


def _mtime(path: Path | None) -> int | None:
    try:
        return path.stat().st_mtime_ns if path is not None else None
    except FileNotFoundError:
        return None


def rules_only_probabilities(values: dict[str, float], rules: RuleSet) -> np.ndarray:
    """Rule-score probabilities as an array in severity order (baseline for evaluation)."""
    evaluation = rules.evaluate(values)
    return np.array([evaluation.probabilities[s] for s in SEVERITY_ORDER])
