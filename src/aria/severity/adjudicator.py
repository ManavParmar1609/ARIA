"""LLM adjudication inside the conformal prediction set.

The model only ever sees a JSON schema whose severity enum is the prediction set, and its answer
is validated again here: a severity outside the set or below the floor, or a citation of
evidence that does not exist, is rejected and repaired or discarded. A compromised or confused
model can therefore pick among the classes the calibrated stages already allow, and nothing
else.

Past incidents like this one that a person reviewed, when memory holds any, go to the model as
fenced, redacted examples with the level the person set (``ReviewedExample``, found by
aria.retrieval.reviewed): how this team rates such incidents. They change nothing about the set.
A reviewed level the set rules out is reported (``examples_outside_set``) so the reviewer hears
of it; the model still cannot choose it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from aria.contracts.base import Claim, Evidence, Severity
from aria.llm.base import BudgetExceededError, LLMError, NoProviderAvailableError
from aria.llm.budget import BudgetGuard
from aria.llm.jsonschema import restrict_enum, strict_schema
from aria.llm.prompts import build_messages
from aria.llm.router import LLMRouter
from aria.llm.schemas import AdjudicationOutput
from aria.severity.policy import Preliminary


@dataclass(frozen=True)
class ReviewedExample:
    """A past incident a person reviewed, with the level the person set. Its text is redacted
    before it is made, and fenced before a model reads it."""

    incident_id: str
    title: str
    summary: str
    failure_mode: str
    severity: Severity  # the level the person set
    aria_severity: Severity | None = None  # the level ARIA had proposed before the review
    decision: str = "approve"
    similarity: float = 0.0
    evidence_id: str | None = None  # the evidence item that lists the examples, to cite


def levels_outside_set(
    examples: Sequence[ReviewedExample], allowed: Sequence[Severity]
) -> list[Severity]:
    """The levels people set on the examples that lie outside ``allowed``, most severe first:
    out of the model's reach, and reported to the reviewer."""
    outside = {example.severity for example in examples if example.severity not in allowed}
    return sorted(outside, key=lambda s: s.rank)


@dataclass
class Adjudication:
    severity: Severity | None
    claims: list[Claim]
    provider: str | None = None
    model: str | None = None
    reason: str | None = None  # why there is no LLM decision, when severity is None
    # Levels people set on the examples that the set rules out: reported, never chosen.
    examples_outside_set: list[Severity] = field(default_factory=list)


def _facts(
    pre: Preliminary,
    system: str,
    features: dict[str, float],
    examples: Sequence[ReviewedExample] = (),
) -> dict[str, object]:
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
        # The trusted part of each example: what a person decided, never what a log said.
        "reviewed_examples": [
            {
                "incident_id": e.incident_id,
                "reviewed_severity": str(e.severity),
                "aria_severity": str(e.aria_severity) if e.aria_severity else None,
                "decision": e.decision,
                "similarity": e.similarity,
                "evidence_id": e.evidence_id,
            }
            for e in examples
        ],
        "reviewed_levels_outside_set": [
            str(s) for s in levels_outside_set(examples, pre.prediction_set)
        ],
    }


def _quoted_examples(examples: Sequence[ReviewedExample]) -> list[dict[str, object]]:
    """The examples' text, which quotes logs and reports: it travels fenced."""
    return [
        {
            "incident_id": e.incident_id,
            "title": e.title,
            "failure_mode": e.failure_mode,
            "summary": e.summary,
            "reviewed_severity": str(e.severity),
        }
        for e in examples
    ]


async def adjudicate(
    pre: Preliminary,
    *,
    system: str,
    features: dict[str, float],
    evidence: Sequence[Evidence],
    router: LLMRouter,
    budget: BudgetGuard | None = None,
    examples: Sequence[ReviewedExample] = (),
) -> Adjudication:
    allowed = pre.prediction_set
    known = {item.id for item in evidence}
    outside = levels_outside_set(examples, allowed)

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
    messages = build_messages(
        "adjudication",
        _facts(pre, system, features, examples),
        evidence,
        untrusted_data={"reviewed_incidents": _quoted_examples(examples)} if examples else None,
    )
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
    except NoProviderAvailableError as exc:
        at_limits = bool(exc.attempts) and all(a.get("skipped") for a in exc.attempts)
        reason = (
            "the models were at their limits" if at_limits else "no LLM adjudicator is configured"
        )
        return Adjudication(None, [], reason=reason, examples_outside_set=outside)
    except BudgetExceededError as exc:
        return Adjudication(
            None, [], reason=f"the run's {exc.reason} budget is spent", examples_outside_set=outside
        )
    except LLMError:
        return Adjudication(
            None, [], reason="the LLM's answers failed validation", examples_outside_set=outside
        )
    claims = [Claim(text=c.text, evidence_ids=c.evidence_ids) for c in result.value.rationale]
    return Adjudication(
        result.value.severity,
        claims,
        result.provider,
        result.model,
        examples_outside_set=outside,
    )
