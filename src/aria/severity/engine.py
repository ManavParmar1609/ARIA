"""The severity agent's core: rules, then the calibrated model, then the decision policy."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

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
from aria.severity.model import LinearModel
from aria.severity.policy import Preliminary, decide
from aria.severity.rules import RuleSet, feature_space, load_rules

log = get_logger(__name__)
RULES_ONLY_MIN_P = 0.2


@dataclass
class SeverityResult:
    assessment: SeverityAssessment
    preliminary: Preliminary
    adjudication: Adjudication | None


class SeverityEngine:
    def __init__(self, rules: RuleSet, model: LinearModel | None, *, alpha: float) -> None:
        self.rules = rules
        self.model = model
        self.alpha = model.alpha if model is not None and model.conformal_q is not None else alpha
        if model is not None and model.classes != [str(s) for s in SEVERITY_ORDER]:
            msg = f"severity model classes {model.classes} do not match {SEVERITY_ORDER}"
            raise ValueError(msg)

    @classmethod
    def load(cls, config: SeverityConfig) -> SeverityEngine:
        rules = load_rules(config.rules_file)
        model = (
            LinearModel.load(config.log_model_file)
            if Path(config.log_model_file).exists()
            else None
        )
        if model is None:
            log.warning("severity.model_missing", path=str(config.log_model_file))
        return cls(rules, model, alpha=config.alpha)

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

        if self.model is None:
            probabilities = evaluation.probabilities
            raw_set = [s for s in SEVERITY_ORDER if probabilities[s] >= RULES_ONLY_MIN_P]
            raw_set = raw_set or [evaluation.rule_severity]
            version, conformal, extra = f"rules-only:{self.rules.version}", False, {}
        else:
            row = log_feature_row(values, evaluation)
            x = self.model.matrix([row])
            probs = self.model.predict_proba(x)[0]
            probabilities = {
                Severity(c): float(p) for c, p in zip(self.model.classes, probs, strict=True)
            }
            raw_set = [Severity(c) for c in self.model.prediction_sets(probs[None, :])[0]]
            top = max(probabilities, key=lambda s: probabilities[s])
            version, conformal = self.model.version, self.model.conformal_q is not None
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
                f"{1 - self.alpha:.0%} prediction set: {{{', '.join(raw_set)}}}"
                if conformal
                else "No calibrated model is loaded; probabilities are normalised rule scores."
            ),
            data={
                "probabilities": {str(k): round(v, 6) for k, v in probabilities.items()},
                "prediction_set": [str(s) for s in raw_set],
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


def rules_only_probabilities(values: dict[str, float], rules: RuleSet) -> np.ndarray:
    """Rule-score probabilities as an array in severity order (baseline for evaluation)."""
    evaluation = rules.evaluate(values)
    return np.array([evaluation.probabilities[s] for s in SEVERITY_ORDER])
