"""The reporter agent: grounded draft, optional LLM narrative, critic, then final validation.

1. Compose the deterministic draft (always grounded).
2. With an LLM, ask it to improve the draft. Its output must pass the same grounding checks
   inside the router's repair loop, or it is discarded.
3. A critic (the LLM critic when one is configured, else the offline lexical check) reviews
   each claim against its cited evidence; claims it flags are removed.
4. Validate the result. If anything still fails, publish the deterministic draft instead.

Nothing a model writes reaches a reviewer without passing step 4.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from aria.contracts.base import Claim, Evidence
from aria.contracts.report import IncidentReport, ValidationIssue, ValidationResult
from aria.llm.base import BudgetExceededError, LLMError, TokenCallback
from aria.llm.budget import BudgetGuard
from aria.llm.prompts import build_messages
from aria.llm.router import LLMRouter
from aria.llm.schemas import CriticIssue, CriticOutput, NarrativeOutput
from aria.reporting.composer import (
    ReportContext,
    compose_draft,
    compose_timeline,
    narrative_to_parts,
)
from aria.reporting.grounding import validate_report
from aria.retrieval.runbooks import Runbook
from aria.security.safety import check_text

FLAGGING = {"unsupported", "contradicted", "overstated", "missing_citation"}


@dataclass
class ReportOutcome:
    report: IncidentReport
    llm_used: bool = False
    provider: str | None = None
    model: str | None = None
    critic: Literal["llm", "offline", "skipped"] = "skipped"
    critic_issues: list[CriticIssue] = field(default_factory=list)
    removed_claims: list[str] = field(default_factory=list)
    fell_back: bool = False
    safety: Literal["passed", "flagged", "skipped"] = "skipped"
    notes: list[str] = field(default_factory=list)


class ReportWriter:
    def __init__(
        self,
        router: LLMRouter | None,
        runbooks: dict[str, Runbook],
        *,
        safety_check: bool = False,
    ) -> None:
        self.router = router
        self.runbooks = runbooks
        self.safety_check = safety_check

    # --- building and validating ---------------------------------------------------------------

    def _build(
        self,
        ctx: ReportContext,
        narrative: NarrativeOutput,
        *,
        report_id: str,
        generated_by: Literal["template", "llm"],
        model: str | None,
    ) -> IncidentReport:
        return IncidentReport(
            report_id=report_id,
            run_id=ctx.run_id,
            severity=ctx.severity.severity,
            timeline=compose_timeline(ctx),
            similar_incidents=list(ctx.retrieval.incidents),
            ticket_history=ctx.retrieval.tickets,
            evidence=list(ctx.evidence),
            generated_by=generated_by,
            model=model,
            **narrative_to_parts(narrative),  # type: ignore[arg-type]
        )

    def validate(
        self, report: IncidentReport, ctx: ReportContext, *, strict: bool = False
    ) -> ValidationResult:
        return validate_report(
            report,
            evidence=ctx.evidence,
            expected_severity=ctx.severity.severity,
            runbooks=self.runbooks,
            strict=strict,
        )

    # --- LLM narrative -------------------------------------------------------------------------

    def _facts(self, ctx: ReportContext) -> dict[str, Any]:
        runbooks = []
        for ref in ctx.retrieval.runbooks:
            runbook = self.runbooks.get(ref.slug)
            if runbook is not None:
                runbooks.append(
                    {
                        "slug": runbook.slug,
                        "title": runbook.title,
                        "steps": [{"text": s.text, "risk": s.risk} for s in runbook.mitigate],
                        "evidence_id": ref.evidence_id,
                    }
                )
        sev = ctx.severity
        return {
            "system": ctx.system,
            "severity": str(sev.severity),
            "decided_by": sev.decided_by,
            "needs_review": sev.needs_review,
            "prediction_set": [str(s) for s in sev.prediction_set],
            "runbooks": runbooks,
            "rules": [
                "Keep the severity exactly as given.",
                "Every claim cites evidence IDs; every number must appear in the cited evidence.",
                "Actions come only from the listed runbooks, keeping each step's risk.",
            ],
        }

    async def _narrative(
        self,
        ctx: ReportContext,
        draft: NarrativeOutput,
        *,
        report_id: str,
        budget: BudgetGuard | None,
        on_token: TokenCallback | None,
        on_reset: Callable[[], None] | None,
        strict: bool,
    ) -> tuple[NarrativeOutput, str, str] | str:
        assert self.router is not None  # noqa: S101 - caller checks

        def check(candidate: NarrativeOutput) -> list[str]:
            report = self._build(
                ctx, candidate, report_id=report_id, generated_by="llm", model=None
            )
            result = self.validate(report, ctx, strict=strict)
            return [f"{i.path or 'report'}: {i.message}" for i in result.errors][:10]

        try:
            result = await self.router.structured(
                "reporter",
                "narrative",
                build_messages(
                    "narrative",
                    self._facts(ctx),
                    ctx.evidence,
                    untrusted_data={"draft": draft.model_dump()},  # it quotes log templates
                ),
                NarrativeOutput,
                validator=check,
                budget=budget,
                on_token=on_token,
                on_reset=on_reset,
                temperature=0.2,
                max_tokens=2_500,
            )
        except BudgetExceededError as exc:
            return f"LLM narrative skipped: the run's {exc.reason} budget is spent"
        except LLMError as exc:
            return f"LLM narrative unavailable: {exc}"
        return result.value, result.provider, f"{result.provider}/{result.model}"

    # --- critic --------------------------------------------------------------------------------

    async def _critic(
        self,
        report: IncidentReport,
        ctx: ReportContext,
        *,
        budget: BudgetGuard | None,
        use_llm: bool,
    ) -> tuple[CriticOutput, Literal["llm", "offline"]]:
        claims = [
            {"path": path, "text": c.text, "evidence_ids": c.evidence_ids}
            for path, c in report.claims()
        ]
        cited = sorted({e for c in claims for e in c["evidence_ids"]})
        evidence = [e for e in ctx.evidence if e.id in cited]
        messages = build_messages("critic", {}, evidence, untrusted_data={"claims": claims})
        if use_llm and self.router is not None and self.router.has_real_llm("critic"):
            try:
                result = await self.router.structured(
                    "critic",
                    "critic",
                    messages,
                    CriticOutput,
                    budget=budget,
                    temperature=0.0,
                    max_tokens=1_200,
                )
                return result.value, "llm"
            except (BudgetExceededError, LLMError):
                pass
        from aria.llm.fake import RESPONDERS  # noqa: PLC0415 - the offline lexical critic
        from aria.llm.prompts import (  # noqa: PLC0415
            parse_context,
            parse_evidence_block,
            parse_untrusted_data,
        )

        ctx_facts = {**parse_context(messages), **parse_untrusted_data(messages)}
        ctx_facts["_evidence_block"] = parse_evidence_block(messages)
        return CriticOutput.model_validate(RESPONDERS["critic"](ctx_facts)), "offline"

    @staticmethod
    def _pin_severity(
        value: NarrativeOutput, draft: NarrativeOutput, ctx: ReportContext
    ) -> NarrativeOutput:
        """The severity statement is mandatory: restore the draft's if the model dropped it."""
        label = str(ctx.severity.severity)
        if any(label in claim.text for claim in value.summary) or not draft.summary:
            return value
        return value.model_copy(update={"summary": [draft.summary[0], *value.summary][:5]})

    @staticmethod
    def _drop_flagged(
        report: IncidentReport, issues: list[CriticIssue]
    ) -> tuple[IncidentReport, list[str]]:
        flagged = {i.path for i in issues if i.problem in FLAGGING}
        removed: list[str] = []
        sections: dict[str, list[Claim]] = {}
        for section in ("summary", "impact", "suspected_cause"):
            kept = []
            for i, claim in enumerate(getattr(report, section)):
                path = f"{section}[{i}]"
                if path in flagged:
                    removed.append(f"{path}: {claim.text[:120]}")
                else:
                    kept.append(claim)
            sections[section] = kept
        if not sections["summary"]:  # the summary may not be empty: keep its first claim
            sections["summary"] = report.summary[:1]
            removed = [r for r in removed if not r.startswith("summary[0]")]
        return report.model_copy(update=sections), removed

    # --- public entry point --------------------------------------------------------------------

    async def write(
        self,
        ctx: ReportContext,
        *,
        report_id: str,
        use_llm: bool = True,
        validation: Literal["standard", "strict"] = "standard",
        budget: BudgetGuard | None = None,
        on_token: TokenCallback | None = None,
        on_reset: Callable[[], None] | None = None,
    ) -> ReportOutcome:
        strict = validation == "strict"
        draft = compose_draft(ctx)
        draft_report = self._build(
            ctx, draft, report_id=report_id, generated_by="template", model=None
        )
        outcome = ReportOutcome(report=draft_report)

        candidate = draft_report
        if use_llm and self.router is not None and self.router.chain("reporter"):
            narrative = await self._narrative(
                ctx,
                draft,
                report_id=report_id,
                budget=budget,
                on_token=on_token,
                on_reset=on_reset,
                strict=strict,
            )
            if isinstance(narrative, str):
                outcome.notes.append(narrative)
            else:
                value, provider, model = narrative
                value = self._pin_severity(value, draft, ctx)
                candidate = self._build(
                    ctx, value, report_id=report_id, generated_by="llm", model=model
                )
                outcome.llm_used, outcome.provider, outcome.model = True, provider, model
                if self.safety_check:
                    text = "\n".join(claim.text for _, claim in candidate.claims())
                    verdict = await check_text(self.router, text, budget=budget)
                    outcome.safety = "passed" if verdict.safe else "flagged"
                    if not verdict.safe:
                        outcome.fell_back = True
                        outcome.notes.append(
                            f"the LLM report was {verdict.describe()}; published the grounded draft"
                        )
                        candidate = draft_report

        review, critic_kind = await self._critic(candidate, ctx, budget=budget, use_llm=use_llm)
        outcome.critic, outcome.critic_issues = critic_kind, list(review.issues)
        if review.issues:
            candidate, outcome.removed_claims = self._drop_flagged(candidate, review.issues)

        result = self.validate(candidate, ctx, strict=strict)
        if not result.ok and candidate.generated_by == "llm":
            outcome.fell_back = True
            outcome.notes.append(
                "the LLM report failed final validation; published the grounded draft"
            )
            candidate = draft_report
            result = self.validate(candidate, ctx, strict=strict)
        critic_notes = [
            ValidationIssue(
                code=f"critic_{i.problem}",
                message=i.explanation or i.problem,
                path=i.path,
                level="warning",
            )
            for i in review.issues
        ]
        result = result.model_copy(update={"issues": [*result.issues, *critic_notes]})
        outcome.report = candidate.model_copy(update={"validation": result})
        return outcome


def cited_evidence(report: IncidentReport) -> list[Evidence]:
    """Evidence items the report actually cites, in citation order."""
    order: list[str] = []
    for _, claim in report.claims():
        order.extend(e for e in claim.evidence_ids if e not in order)
    for entry in report.timeline:
        order.extend(e for e in entry.evidence_ids if e not in order)
    for action in report.actions:
        order.extend(e for e in action.evidence_ids if e not in order)
    by_id = {e.id: e for e in report.evidence}
    return [by_id[e] for e in order if e in by_id]
