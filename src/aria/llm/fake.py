"""Deterministic offline provider.

It answers from the same ``<aria_context>`` facts a real model receives, so tests, evals and
the offline demo exercise the real prompt contract, validation and repair paths. Tests can also
queue raw outputs (including malformed ones) or errors per task to drive failure paths.

Its outputs are never presented as a real model's: results carry provider ``fake``.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from aria.config import ProviderKind
from aria.contracts.base import Severity
from aria.llm.base import Message, ProviderError, TokenCallback, Usage, estimate_tokens
from aria.llm.prompts import parse_context

Responder = Callable[[dict[str, Any]], dict[str, Any]]
_WORD = re.compile(r"[a-z0-9_]{3,}")


def _ids(ctx: dict[str, Any], *kinds: str) -> list[str]:
    return [e["id"] for e in ctx.get("evidence_index", []) if not kinds or e.get("kind") in kinds]


def _first(*candidates: Iterable[str]) -> list[str]:
    for candidate in candidates:
        items = [c for c in candidate if c]
        if items:
            return items[:3]
    return []


def _adjudication(ctx: dict[str, Any]) -> dict[str, Any]:
    pset = [Severity(s) for s in ctx.get("prediction_set") or ["SEV2"]]
    floor = Severity(ctx["floor"]) if ctx.get("floor") else None
    allowed = [s for s in pset if floor is None or s.rank <= floor.rank] or [
        min(pset, key=lambda s: s.rank)
    ]
    probs = {Severity(k): float(v) for k, v in (ctx.get("probabilities") or {}).items()}
    choice = max(allowed, key=lambda s: (round(probs.get(s, 0.0), 6), -s.rank))
    model_ev = _first([ctx.get("model_evidence_id") or ""], _ids(ctx, "model"), _ids(ctx))
    rationale = [
        {
            "text": f"Within the prediction set {', '.join(pset)}, the calibrated model rates "
            f"{choice} most likely (p={probs.get(choice, 0.0):.2f}).",
            "evidence_ids": model_ev,
        }
    ]
    hits = [h for h in ctx.get("rule_hits", []) if h.get("evidence_ids")]
    if hits:
        top = min(hits, key=lambda h: Severity(h["severity"]).rank)
        rationale.append(
            {
                "text": f"Rule '{top['title']}' points to {top['severity']}.",
                "evidence_ids": top["evidence_ids"][:3],
            }
        )
    uncertainty = "" if len(pset) == 1 else f"The set still contains {len(pset)} severities."
    return {"severity": str(choice), "rationale": rationale, "uncertainty": uncertainty}


def _investigator_step(ctx: dict[str, Any]) -> dict[str, Any]:
    allowed = set(ctx.get("allowed_actions", []))
    done = {obs.get("tool") for obs in ctx.get("observations", [])}
    hypotheses = ctx.get("hypotheses", [])
    new = []
    if not hypotheses:
        new = [
            {
                "statement": c["statement"],
                "failure_mode": c["failure_mode"],
                "component": c.get("component"),
            }
            for c in ctx.get("candidate_hypotheses", [])[:2]
        ]
    updates = []
    observations = ctx.get("observations", [])
    if hypotheses and observations:
        lead = hypotheses[0]
        supporting = [e for obs in observations for e in obs.get("evidence_ids", [])][:6]
        if supporting:
            updates.append(
                {
                    "id": lead["id"],
                    "status": "supported" if len(observations) >= 2 else "open",
                    "confidence": min(0.9, 0.5 + 0.15 * len(observations)),
                    "supporting": supporting,
                    "refuting": [],
                }
            )
    action = "finish"
    planned_args: dict[str, Any] = {}
    remaining = int(ctx.get("max_steps", 0)) - int(ctx.get("step", 0))
    if remaining > 0:
        for planned in ctx.get("suggested_plan", []):
            if planned.get("tool") in allowed and planned.get("tool") not in done:
                action, planned_args = planned["tool"], planned.get("arguments") or {}
                break
    arguments = {
        key: planned_args.get(key)
        for key in ("query", "template_id", "component", "node", "failure_mode", "slug", "limit")
    }
    rationale = (
        "Enough evidence gathered; finishing."
        if action == "finish"
        else f"Next, check {action} to test the leading hypothesis."
    )
    return {
        "rationale": rationale,
        "new_hypotheses": new,
        "updates": updates,
        "action": action,
        "arguments": arguments,
    }


def _narrative(ctx: dict[str, Any]) -> dict[str, Any]:
    draft = dict(ctx.get("draft") or {})
    if not draft.get("summary"):
        ids = _ids(ctx)[:2]
        draft["summary"] = [
            {"text": "ARIA collected evidence for this incident.", "evidence_ids": ids}
        ]
    draft.setdefault(
        "title", f"{ctx.get('severity', 'SEV3')} incident on {ctx.get('system', 'unknown system')}"
    )
    for key in ("impact", "suspected_cause", "actions", "open_questions"):
        draft.setdefault(key, [])
    return draft


def _overlap(claim: str, evidence_text: str) -> float:
    claim_words = set(_WORD.findall(claim.lower()))
    if not claim_words:
        return 1.0
    return len(claim_words & set(_WORD.findall(evidence_text.lower()))) / len(claim_words)


def _critic(ctx: dict[str, Any]) -> dict[str, Any]:
    known = set(_ids(ctx))
    texts: dict[str, str] = ctx.get("evidence_text", {})
    issues = []
    for claim in ctx.get("claims", []):
        cited = claim.get("evidence_ids", [])
        if not cited:
            issues.append(
                {
                    "path": claim["path"],
                    "problem": "missing_citation",
                    "explanation": "No evidence cited.",
                    "suggested_evidence_ids": [],
                }
            )
            continue
        if any(e not in known for e in cited):
            issues.append(
                {
                    "path": claim["path"],
                    "problem": "unsupported",
                    "explanation": "Cites unknown evidence.",
                    "suggested_evidence_ids": [],
                }
            )
            continue
        support = " ".join(texts.get(e, "") for e in cited)
        if support and _overlap(claim.get("text", ""), support) < 0.08:
            issues.append(
                {
                    "path": claim["path"],
                    "problem": "unsupported",
                    "explanation": "Cited evidence shares almost no terms with the claim.",
                    "suggested_evidence_ids": [],
                }
            )
    return {"verdict": "revise" if issues else "pass", "issues": issues}


def _comms(ctx: dict[str, Any]) -> dict[str, Any]:
    drafts = ctx.get("drafts") or {}
    ids = _ids(ctx)[:2]
    fallback = {
        "title": ctx.get("title", "Incident update"),
        "body": "We are investigating an incident.",
        "evidence_ids": ids,
    }
    return {
        key: drafts.get(key) or fallback for key in ("responders", "stakeholders", "status_page")
    }


def _answer(ctx: dict[str, Any]) -> dict[str, Any]:
    ranked: list[dict[str, Any]] = ctx.get("ranked_evidence", [])
    if not ranked:
        return {
            "answer": [],
            "insufficient_evidence": True,
            "follow_ups": ["Which run or incident do you mean?"],
        }
    answer = [{"text": item["summary"], "evidence_ids": [item["id"]]} for item in ranked[:3]]
    return {"answer": answer, "insufficient_evidence": False, "follow_ups": []}


def _query_rewrite(ctx: dict[str, Any]) -> dict[str, Any]:
    terms: list[str] = []
    for key in ("failure_mode_hints", "components", "keywords", "template_terms"):
        for term in ctx.get(key, []):
            if term and term not in terms:
                terms.append(str(term))
    query = " ".join(terms[:12]) or str(ctx.get("query") or "error failure")
    hints = ctx.get("failure_mode_hints") or [None]
    return {"query": query[:300], "system": ctx.get("system"), "failure_mode": hints[0]}


RESPONDERS: dict[str, Responder] = {
    "adjudication": _adjudication,
    "investigator_step": _investigator_step,
    "narrative": _narrative,
    "critic": _critic,
    "comms": _comms,
    "answer": _answer,
    "query_rewrite": _query_rewrite,
}


class FakeProvider:
    """Offline provider. ``script`` queues raw outputs or exceptions per task for tests."""

    kind = ProviderKind.FAKE

    def __init__(
        self,
        name: str = "fake",
        *,
        model: str = "aria-fake-1",
        script: dict[str, Sequence[str | BaseException]] | None = None,
        responders: dict[str, Responder] | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._script: dict[str, deque[str | BaseException]] = defaultdict(deque)
        for task, outputs in (script or {}).items():
            self._script[task].extend(outputs)
        self.responders = {**RESPONDERS, **(responders or {})}
        self.calls: list[dict[str, Any]] = []

    def queue(self, task: str, *outputs: str | BaseException) -> None:
        self._script[task].extend(outputs)

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "output",
        temperature: float = 0.0,
        max_tokens: int = 1_500,
        on_token: TokenCallback | None = None,
        model: str | None = None,
    ) -> tuple[str, Usage]:
        del temperature, max_tokens
        self.calls.append(
            {"task": schema_name, "messages": list(messages), "model": model or self.model}
        )
        queued = self._script.get(schema_name)
        if queued:
            item = queued.popleft()
            if isinstance(item, BaseException):
                raise item
            text = item
        elif json_schema is None:
            text = "ARIA offline model: no free-text responder is configured."
        else:
            responder = self.responders.get(schema_name)
            if responder is None:
                msg = f"fake provider has no responder for task {schema_name!r}"
                raise ProviderError(msg, status=400)
            text = json.dumps(responder(parse_context(messages)), ensure_ascii=False)
        if on_token is not None:
            for piece in re.findall(r"\S+\s*", text):
                on_token(piece)
        usage = Usage(
            input_tokens=sum(estimate_tokens(m.content) for m in messages),
            output_tokens=estimate_tokens(text),
            cost_usd=0.0,
            estimated=True,
        )
        return text, usage
