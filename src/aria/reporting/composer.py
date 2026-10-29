"""Deterministic report drafts.

The composer turns the run's evidence into a complete first-pass report with no model at all.
Every sentence is built from an evidence item and cites it, and every number it writes is copied
from that evidence, so the draft passes the grounding checks by construction. It is the report
ARIA publishes when no LLM is configured, the fallback when an LLM's report fails validation,
and the draft an LLM is asked to improve.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from aria.contracts.base import SEVERITY_DESCRIPTIONS, Claim, Evidence, EvidenceKind, Severity
from aria.contracts.inputs import AlertSignal
from aria.contracts.parsing import ParsedBatch
from aria.contracts.report import ActionItem, TimelineEntry
from aria.contracts.retrieval import Hypothesis, Investigation, RetrievalResult
from aria.contracts.severity import SeverityAssessment
from aria.llm.schemas import ActionOut, ClaimOut, NarrativeOutput
from aria.retrieval.runbooks import Runbook

DECIDED_BY_TEXT = {
    "rules": "decided by rules",
    "model": "decided by the calibrated model",
    "llm": "chosen by the LLM within the model's prediction set",
    "fallback": "most severe option in the prediction set, pending review",
    "human": "set by a reviewer",
}
SYSTEM_NAMES = {
    "bgl": "BlueGene/L",
    "hdfs": "HDFS",
    "hadoop": "Hadoop",
    "zookeeper": "ZooKeeper",
    "openssh": "OpenSSH",
    "linux": "Linux",
    "hpc": "HPC",
    "openstack": "OpenStack",
    "apache": "Apache",
    "proxifier": "Proxifier",
    "thunderbird": "Thunderbird",
    "mac": "macOS",
    "android": "Android",
    "spark": "Spark",
    "windows": "Windows",
    "healthapp": "HealthApp",
}


@dataclass
class ReportContext:
    run_id: str
    system: str
    batch: ParsedBatch
    severity: SeverityAssessment
    evidence: list[Evidence]
    retrieval: RetrievalResult = field(default_factory=RetrievalResult)
    investigation: Investigation = field(default_factory=Investigation)
    alerts: list[AlertSignal] = field(default_factory=list)
    runbooks: dict[str, Runbook] = field(default_factory=dict)
    service: str | None = None
    title_hint: str | None = None

    @property
    def by_id(self) -> dict[str, Evidence]:
        return {item.id: item for item in self.evidence}

    def find(
        self, kind: EvidenceKind, *, source: str | None = None, key: str | None = None
    ) -> Evidence | None:
        for item in self.evidence:
            if (
                item.kind is kind
                and (source is None or item.source == source)
                and (key is None or key in item.data)
            ):
                return item
        return None

    def all_of(self, kind: EvidenceKind, *, source: str | None = None) -> list[Evidence]:
        return [
            i for i in self.evidence if i.kind is kind and (source is None or i.source == source)
        ]

    @property
    def system_name(self) -> str:
        return SYSTEM_NAMES.get(self.system, self.system)

    @property
    def leading(self) -> Hypothesis | None:
        hypotheses = self.investigation.hypotheses
        lead = next((h for h in hypotheses if h.id == self.investigation.leading_hypothesis), None)
        supported = [h for h in hypotheses if h.status == "supported"]
        return lead or (max(supported, key=lambda h: h.confidence) if supported else None)


def _ids(*items: Evidence | None) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item is not None and item.id not in seen:
            seen.append(item.id)
    return seen[:8]


def _claim(text: str, *items: Evidence | None) -> ClaimOut | None:
    ids = _ids(*items)
    return ClaimOut(text=text[:600], evidence_ids=ids) if ids else None


def _mode_words(mode: str) -> str:
    return mode.replace("_", " ").strip()


def compose_title(ctx: ReportContext) -> str:
    if ctx.title_hint:
        return f"{ctx.severity.severity} · {ctx.title_hint}"[:140]
    features = ctx.batch.features
    lead = ctx.leading
    top = ctx.retrieval.incidents[0] if ctx.retrieval.incidents else None
    if lead is not None:
        what = _mode_words(lead.failure_mode).capitalize()
    elif top is not None and top.score > 0:
        what = f"Suspected {_mode_words(top.failure_mode)}"
    elif features.error_events:
        what = "Error spike"
    else:
        what = "Log anomaly check"
    where = f"{ctx.system_name}" + (f" ({ctx.service})" if ctx.service else "")
    nodes = f" on {features.error_nodes} nodes" if features.error_nodes > 1 else ""
    return f"{ctx.severity.severity} · {what} in {where}{nodes}"[:140]


def compose_draft(ctx: ReportContext) -> NarrativeOutput:
    features = ctx.batch.features
    sev = ctx.severity
    model_ev = ctx.find(EvidenceKind.MODEL, source="severity.model")
    rule_evs = ctx.all_of(EvidenceKind.RULE, source="severity.rules")
    window = ctx.find(EvidenceKind.FEATURE, source="parser", key="n_events")
    burst = ctx.find(EvidenceKind.FEATURE, source="parser", key="burst_score")
    spread = ctx.find(EvidenceKind.FEATURE, source="parser", key="error_nodes")
    floor_ev = next((e for e in rule_evs if e.data.get("effect") == "floor"), None)
    by_id = ctx.by_id

    summary: list[ClaimOut | None] = []
    p = sev.probabilities.get(sev.severity, 0.0)
    how = DECIDED_BY_TEXT[sev.decided_by]
    severity_text = f"{sev.severity}: {SEVERITY_DESCRIPTIONS[sev.severity]} Severity {how}"
    if sev.decided_by in ("model", "llm", "fallback") and model_ev is not None:
        severity_text += f" (model probability {p:.2f})"
    summary.append(
        _claim(f"{severity_text}.", model_ev, floor_ev or (rule_evs[0] if rule_evs else None))
    )
    if window is not None and features.n_events:
        scale = (
            f"{features.error_events} error events ({features.error_ratio:.1%} of {features.n_events}) "
            f"in {features.duration_s / 60:.1f} minutes of logs"
        )
        if spread is not None:
            scale += f", on {features.error_nodes} of {features.distinct_nodes} nodes"
        summary.append(_claim(f"{scale}.", window, spread))
    if burst is not None and features.burst_score >= 2:
        summary.append(
            _claim(
                f"Errors peaked at {features.peak_errors_per_min:.0f} per minute "
                f"(burst score {features.burst_score:.1f}).",
                burst,
            )
        )
    top_error = next(
        (t for t in ctx.batch.templates if t.error_like and t.evidence_id in by_id), None
    )
    if top_error is not None:
        summary.append(
            _claim(
                f'Most frequent error: "{top_error.template[:160]}" ({top_error.count} lines on {top_error.nodes} nodes).',
                by_id[top_error.evidence_id],
            )
        )
    incidents = [i for i in ctx.retrieval.incidents if i.evidence_id in by_id]
    if incidents:
        best = incidents[0]
        seen = f"seen {best.occurrences} times" if best.occurrences > 1 else "seen once"
        summary.append(
            _claim(
                f"Closest past incident: {best.title} ({best.severity}, {seen}).",
                by_id[best.evidence_id or ""],
            )
        )

    impact: list[ClaimOut | None] = []
    if spread is not None and features.critical_components:
        impact.append(
            _claim(
                f"Critical components logging errors: {', '.join(features.critical_components[:4])}.",
                spread,
            )
        )
    if spread is not None and features.node_spread >= 0.5:
        impact.append(
            _claim(f"Errors span {features.node_spread:.0%} of the nodes in this window.", spread)
        )
    if ctx.retrieval.tickets is not None and ctx.retrieval.tickets.evidence_id in by_id:
        t = ctx.retrieval.tickets
        if t.sla_breach_rate is not None:
            impact.append(
                _claim(
                    f"Similar ITSM tickets breached their SLA in {t.sla_breach_rate:.0%} of {t.n_similar} cases.",
                    by_id[t.evidence_id or ""],
                )
            )
    alert_evs = ctx.all_of(EvidenceKind.ALERT)
    if alert_evs:
        names = (
            ", ".join(sorted({a.name for a in ctx.alerts if a.status == "firing"})[:4])
            or "monitoring alerts"
        )
        impact.append(_claim(f"Firing alerts: {names}.", *alert_evs[:4]))

    cause: list[ClaimOut | None] = []
    lead = ctx.leading
    if lead is not None:
        supporting = [by_id[e] for e in lead.supporting if e in by_id]
        hyp_ev = next(
            (e for e in ctx.all_of(EvidenceKind.HYPOTHESIS) if e.data.get("id") == lead.id), None
        )
        text = f"Suspected cause: {lead.statement.rstrip('.')}"
        if hyp_ev is not None and "confidence" in hyp_ev.data:
            # Quote the confidence only from the evidence that records it.
            text += f" (investigation confidence {float(hyp_ev.data['confidence']):.0%})"
        cause.append(_claim(f"{text}.", hyp_ev, *supporting[:4]))
    elif incidents:
        best = incidents[0]
        agreeing = [i for i in incidents if i.failure_mode == best.failure_mode]
        cause.append(
            _claim(
                f"Likely {_mode_words(best.failure_mode)}: it matches {len(agreeing)} of the "
                f"{len(incidents)} closest past incidents.",
                *[by_id[i.evidence_id or ""] for i in agreeing],
            )
        )

    actions: list[ActionOut] = []
    for ref in ctx.retrieval.runbooks[:2]:
        runbook = ctx.runbooks.get(ref.slug)
        if runbook is None or ref.evidence_id not in by_id:
            continue
        steps = runbook.mitigate[:1] if runbook.generic else runbook.mitigate[:2]
        actions.extend(
            ActionOut(
                text=step.text,
                runbook_slug=runbook.slug,
                risk=step.risk,
                evidence_ids=[ref.evidence_id or ""],
            )
            for step in steps
        )
    if sev.needs_review and model_ev is not None:
        options = " or ".join(sev.prediction_set)
        actions.insert(
            0,
            ActionOut(
                text=f"Confirm the severity: ARIA could not choose confidently between {options}.",
                risk="low",
                evidence_ids=[model_ev.id],
            ),
        )
    injection_evs = ctx.all_of(EvidenceKind.LOG, source="guardrail")
    if injection_evs:
        actions.insert(
            0,
            ActionOut(
                text="Review the quarantined log lines: they look like a prompt-injection attempt and were excluded from analysis.",
                risk="low",
                evidence_ids=[e.id for e in injection_evs[:3]],
            ),
        )

    questions: list[str] = []
    if not incidents or ctx.retrieval.grade < 0.35:
        questions.append("No close match in incident memory. Is this a new failure mode?")
    if len(sev.prediction_set) > 1:
        questions.append(f"Is the impact closer to {' or '.join(sev.prediction_set)}?")
    if lead is None and ctx.investigation.hypotheses:
        questions.append(
            "The investigation did not confirm a cause. What changed just before the errors began?"
        )

    return NarrativeOutput(
        title=compose_title(ctx),
        summary=[c for c in summary if c is not None] or [_fallback_claim(ctx)],
        impact=[c for c in impact if c is not None][:4],
        suspected_cause=[c for c in cause if c is not None][:4],
        actions=actions[:6],
        open_questions=questions[:4],
    )


def _fallback_claim(ctx: ReportContext) -> ClaimOut:
    first = ctx.evidence[0]
    return ClaimOut(
        text=f"ARIA analysed the {ctx.system_name} logs for this run.", evidence_ids=[first.id]
    )


def compose_timeline(ctx: ReportContext, *, limit: int = 12) -> list[TimelineEntry]:
    by_id = ctx.by_id
    events: list[tuple[datetime, str, str]] = [
        (t.first_ts, f'First "{t.template[:100]}" ({t.count} lines)', t.evidence_id)
        for t in ctx.batch.templates
        if t.error_like and t.first_ts and t.evidence_id in by_id
    ]
    events.extend(
        (item.ts, f"Error logged: {item.title.split(': ', 1)[-1][:120]}", item.id)
        for item in ctx.all_of(EvidenceKind.LOG, source="parser")
        if item.ts is not None
    )
    events.extend(
        (item.ts, f"Alert fired: {item.title[:120]}", item.id)
        for item in ctx.all_of(EvidenceKind.ALERT)
        if item.ts is not None
    )
    seen: set[tuple[datetime, str]] = set()
    entries = []
    for ts, text, eid in sorted(events, key=lambda e: e[0]):
        if (ts, text) in seen:
            continue
        seen.add((ts, text))
        entries.append(TimelineEntry(ts=ts, text=text, evidence_ids=[eid]))
    return entries[:limit]


def narrative_to_parts(narrative: NarrativeOutput) -> dict[str, object]:
    """Convert LLM/draft output into IncidentReport fields."""
    return {
        "title": narrative.title,
        "summary": [Claim(text=c.text, evidence_ids=c.evidence_ids) for c in narrative.summary],
        "impact": [Claim(text=c.text, evidence_ids=c.evidence_ids) for c in narrative.impact],
        "suspected_cause": [
            Claim(text=c.text, evidence_ids=c.evidence_ids) for c in narrative.suspected_cause
        ],
        "actions": [
            ActionItem(
                text=a.text, runbook_slug=a.runbook_slug, risk=a.risk, evidence_ids=a.evidence_ids
            )
            for a in narrative.actions
        ],
        "open_questions": list(narrative.open_questions),
    }


def severity_rank_text(severity: Severity) -> str:
    return SEVERITY_DESCRIPTIONS[severity].split(":", 1)[0]


__all__ = [
    "DECIDED_BY_TEXT",
    "ReportContext",
    "compose_draft",
    "compose_timeline",
    "compose_title",
    "narrative_to_parts",
    "severity_rank_text",
]
