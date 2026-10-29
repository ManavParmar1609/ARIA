"""The severity agent's core: rules, then the calibrated model, then the decision policy."""

from __future__ import annotations

from collections.abc import Sequence
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
from aria.severity.adjudicator import Adjudication, adjudicate
from aria.severity.features import log_feature_row
from aria.severity.model import LinearModel, live_model_path
from aria.severity.policy import Preliminary, decide
from aria.severity.rules import RuleSet, feature_space, load_rules

log = get_logger(__name__)
RULES_ONLY_MIN_P = 0.2
# How far (in training standard deviations) a window's features may sit from the training mean
# before the model is not used. No training or held-out window reaches it; a handful of lines or
# an alert with no logs is far past it.
MODEL_RANGE_Z = 6.0


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
    ) -> None:
        self.rules = rules
        self.default_alpha = alpha
        self.model_path = model_path
        self._model_mtime = _mtime(model_path)
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
        path = live if live.exists() else trained
        model = LinearModel.load(path) if path.exists() else None
        if model is None:
            log.warning("severity.model_missing", path=str(path))
        return cls(rules, model, alpha=config.alpha, model_path=live)

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
        self._set_model(model)
        self._model_mtime = mtime
        log.info("severity.model_reloaded", version=model.version)
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

    def preliminary(
        self,
        features: WindowFeatures,
        *,
        alerts: Sequence[AlertSignal] = (),
        evidence: EvidenceStore,
        related: Sequence[str] = (),
    ) -> Preliminary:
        self.refresh()
        values = feature_space(features, alerts)
        evaluation = self.rules.evaluate(values)
        hits: list[RuleHit] = []
        rule_ids: list[str] = []
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
        extra: dict[str, Any] = {}
        if self.model is not None:
            x = self.model.matrix([log_feature_row(values, evaluation)])
            outside = self.model.outside_training(x[0], MODEL_RANGE_Z)
        if self.model is None or outside:
            probabilities = evaluation.probabilities
            raw_set = [s for s in SEVERITY_ORDER if probabilities[s] >= RULES_ONLY_MIN_P]
            set_empty = not raw_set
            raw_set = raw_set or [evaluation.rule_severity]
            version, conformal = f"rules-only:{self.rules.version}", False
            if outside:
                extra = {"outside_training": outside[:6]}
        else:
            probs = self.model.predict_proba(x)[0]
            probabilities = {
                Severity(c): float(p) for c, p in zip(self.model.classes, probs, strict=True)
            }
            raw_set = [Severity(c) for c in self.model.prediction_sets(probs[None, :])[0]]
            top = max(probabilities, key=lambda s: probabilities[s])
            version, conformal = self.model.version, self.model.conformal_q is not None
            q = self.model.conformal_q
            set_empty = q is not None and not any(float(p) >= 1.0 - q for p in probs)
            extra = {
                "conformal_q": self.model.conformal_q,
                "temperature": round(self.model.temperature, 4),
                "top_contributions": self.model.contributions(x[0], str(top)),
            }
        shown = ", ".join(f"{s} {probabilities[s]:.2f}" for s in SEVERITY_ORDER)
        model_eid = evidence.add(
            EvidenceKind.MODEL,
            f"Severity probabilities: {shown}",
            source="severity.model",
            detail=(
                (
                    f"No severity is likely enough for the {1 - self.alpha:.0%} prediction set on "
                    f"its own; it falls back to the most likely class, {raw_set[0]}."
                    if set_empty
                    else f"{1 - self.alpha:.0%} prediction set: {{{', '.join(raw_set)}}}"
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
        )

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
    ) -> SeverityResult:
        pre = self.preliminary(features, alerts=alerts, evidence=evidence, related=related)
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
        values = feature_space(features, alerts)
        result = await adjudicate(
            pre,
            system=system,
            features={k: v for k, v in values.items() if v},
            evidence=evidence.all(),
            router=router,
            budget=budget,
        )
        assessment = decide(
            pre,
            gate=self.gate,
            llm_choice=result.severity,
            llm_claims=result.claims,
            llm_unavailable_reason=result.reason,
        )
        return SeverityResult(assessment, pre, result)


def _mtime(path: Path | None) -> int | None:
    try:
        return path.stat().st_mtime_ns if path is not None else None
    except FileNotFoundError:
        return None


def rules_only_probabilities(values: dict[str, float], rules: RuleSet) -> np.ndarray:
    """Rule-score probabilities as an array in severity order (baseline for evaluation)."""
    evaluation = rules.evaluate(values)
    return np.array([evaluation.probabilities[s] for s in SEVERITY_ORDER])
