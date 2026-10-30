"""LLM adjudication inside the conformal prediction set.

The model only ever sees a JSON schema whose severity enum is the prediction set, and its answer
is validated again here: a severity outside the set or below the floor, or a citation of
evidence that does not exist, is rejected and repaired or discarded. A compromised or confused
model can therefore pick among the classes the calibrated stages already allow, and nothing
else.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from aria.contracts.base import Claim, Evidence, Severity
from aria.llm.base import BudgetExceededError, LLMError, NoProviderAvailableError
from aria.llm.budget import BudgetGuard
from aria.llm.jsonschema import restrict_enum, strict_schema
from aria.llm.prompts import build_messages
from aria.llm.router import LLMRouter
from aria.llm.schemas import AdjudicationOutput
from aria.severity.policy import Preliminary


@dataclass
class Adjudication:
    severity: Severity | None
    claims: list[Claim]
    provider: str | None = None
    model: str | None = None
    reason: str | None = None  # why there is no LLM decision, when severity is None


def _facts(pre: Preliminary, system: str, features: dict[str, float]) -> dict[str, object]:
    return {
        "system": system,
        "prediction_set": [str(s) for s in pre.prediction_set],
        "floor": str(pre.floor) if pre.floor else None,
        "probabilities": {str(k): round(v, 4) for k, v in pre.probabilities.items()},
        "rule_severity": str(pre.rule_severity),
        "rule_hits": [
            {
                "rule_id": hit.rule_id,
                "title": hit.title,
                "severity": str(hit.severity),
                "effect": hit.effect,
                "detail": hit.detail,
                "evidence_ids": hit.evidence_ids,
            }
            for hit in pre.rule_hits
        ],
        "model_evidence_id": pre.model_evidence,
        "features": {k: round(v, 3) for k, v in features.items()},
    }


async def adjudicate(
    pre: Preliminary,
    *,
    system: str,
    features: dict[str, float],
    evidence: Sequence[Evidence],
    router: LLMRouter,
    budget: BudgetGuard | None = None,
) -> Adjudication:
    allowed = pre.prediction_set
    known = {item.id for item in evidence}

    def check(output: AdjudicationOutput) -> list[str]:
        errors = []
        if output.severity not in allowed:
            errors.append(f"severity must be one of {', '.join(allowed)}; got {output.severity}")
        cited = {eid for claim in output.rationale for eid in claim.evidence_ids}
        errors.extend(f"evidence {eid} does not exist" for eid in sorted(cited - known))
        return errors

    schema = restrict_enum(
        strict_schema(AdjudicationOutput), ["severity"], [str(s) for s in allowed]
    )
    messages = build_messages("adjudication", _facts(pre, system, features), evidence)
    try:
        result = await router.structured(
            "adjudicator",
            "adjudication",
            messages,
            AdjudicationOutput,
            json_schema=schema,
            validator=check,
            budget=budget,
            temperature=0.0,
            max_tokens=700,
        )
    except NoProviderAvailableError:
        return Adjudication(None, [], reason="no LLM adjudicator is configured")
    except BudgetExceededError as exc:
        return Adjudication(None, [], reason=f"the run's {exc.reason} budget is spent")
    except LLMError:
        return Adjudication(None, [], reason="the LLM's answers failed validation")
    claims = [Claim(text=c.text, evidence_ids=c.evidence_ids) for c in result.value.rationale]
    return Adjudication(result.value.severity, claims, result.provider, result.model)
