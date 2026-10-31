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
from aria.contracts.parsing import ParsedBatch, TemplateStat, WindowFeatures
from aria.contracts.report import ActionItem, TimelineEntry
from aria.contracts.retrieval import Hypothesis, Investigation, RetrievalResult
from aria.contracts.severity import SeverityAssessment
from aria.llm.schemas import ActionOut, ClaimOut, NarrativeOutput
from aria.parsing.catalog import load_lexicon
from aria.parsing.signals import signal_components, signal_templates
from aria.retrieval.runbooks import Runbook
from aria.text import clip, headline, plain_template, sentence_start

# The next step that asks a person to settle a severity ARIA was unsure of; a review that
# approves the report takes it (``reporting.review``).
CONFIRM_SEVERITY = "Confirm the severity"

# How the severity was settled, in the words the console uses for the same five cases.
DECIDED_BY_TEXT = {
    "rules": "A rule set it",
    "model": "The severity model is confident in it",
    "llm": "A language model chose it from the levels the model allowed",
    "fallback": (
        "ARIA is not sure enough to decide alone, so it plans for the most serious level it "
        "could be, and a person confirms"
    ),
    "human": "Set by a reviewer",
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


def _count(n: int, noun: str) -> str:
    """A count with its noun in the right number: "1 node", "3 nodes"."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _claim(text: str, *items: Evidence | None) -> ClaimOut | None:
    ids = _ids(*items)
    return ClaimOut(text=clip(text, 600), evidence_ids=ids) if ids else None


# Failure modes as people write them; the rest read fine with spaces for underscores.
_MODE_WORDS = {
    "auth_failures": "authentication failures",
    "bruteforce": "brute-force attempts",
    "dns_resolution": "DNS resolution failures",
    "hdfs_lease_renewal": "HDFS lease renewal failures",
    "mod_jk_worker_error": "worker errors in mod_jk",
    "psu_failure": "PSU failure",
    "resourcemanager_unreachable": "ResourceManager unreachable",
}


def _mode_words(mode: str) -> str:
    return _MODE_WORDS.get(mode, mode.replace("_", " ").strip())


def _sentence(text: str) -> str:
    """Capitalise the first letter only, so "DNS" and "ResourceManager" keep their case."""
    return text[:1].upper() + text[1:]


def _own_evidence(ctx: ReportContext, template: TemplateStat) -> Evidence | None:
    """The template's own evidence item: it records the count and node spread a claim quotes.
    Templates past the evidence cap point at the window's evidence instead, which does not."""
    item = ctx.by_id.get(template.evidence_id)
    return item if item is not None and item.kind is EvidenceKind.TEMPLATE else None


def _example(ctx: ReportContext, template: TemplateStat) -> Evidence | None:
    """A real line of the template, as the log-line evidence the parser kept for it, if any."""
    return next(
        (
            e
            for e in ctx.all_of(EvidenceKind.LOG, source="parser")
            if e.data.get("template_id") == template.template_id
        ),
        None,
    )


# A report's summary holds at most this many claims (NarrativeOutput enforces it).
SUMMARY_LIMIT = 5


def _at_most(limit: int, claims: list[ClaimOut], burst: Evidence | None) -> list[ClaimOut]:
    """The summary within its limit: the burst rate goes first, as the least telling line, then
    the last ones."""
    if len(claims) > limit and burst is not None:
        claims = [c for c in claims if burst.id not in c.evidence_ids] or claims
    return claims[:limit]


# Kinds of line that decide an incident however rarely they appear: a crash, data at risk, or a
# resource run out.
_DECISIVE = ("crash", "data_risk", "resource")


def _most_serious(
    ctx: ReportContext, signal: list[TemplateStat], quoted: TemplateStat | None
) -> tuple[TemplateStat, Evidence] | None:
    """The strongest signal template, other than the one already quoted, whose lines say a
    process crashed, data is at risk or a resource ran out, with its own evidence."""
    lexicon = load_lexicon()
    decisive = [lexicon[name] for name in _DECISIVE if name in lexicon]
    for template in signal:
        if quoted is not None and template.template_id == quoted.template_id:
            continue
        text = template.template.lower()
        if any(pattern.search(text) for pattern in decisive):
            item = _own_evidence(ctx, template)
            if item is not None:
                return template, item
    return None


def _quoted(item: Evidence) -> str:
    """The log line a log-line evidence item holds (its title reads "line N: <line>"), with an
    ellipsis where the title cut it short, so a cut quote does not read as the whole line."""
    text = item.title.split(": ", 1)[-1]
    full = item.detail or ""
    if len(full) > len(text) and full.startswith(text.rstrip("…")):
        return text if text.endswith("…") else f"{text.rstrip()}…"
    return text


# A title's words for the kind of trouble a window's error lines report most.
_TROUBLE = {
    "crash": "Crashes",
    "data_risk": "Data-integrity errors",
    "unavailable": "Services unreachable",
    "resource": "Resources running out",
    "security": "Sign-in and access failures",
    "hardware": "Hardware errors",
    "storage": "Storage errors",
    "network": "Network errors",
    "degradation": "Slow or retrying requests",
}


def compose_title(ctx: ReportContext) -> str:
    if ctx.title_hint:
        return clip(f"{ctx.severity.severity} · {ctx.title_hint}", 140)
    features = ctx.batch.features
    lead = ctx.leading
    top = next(
        (
            i
            for i in ctx.retrieval.incidents[:1]
            if i.applies_to(ctx.system, ctx.batch.features.components)
        ),
        None,
    )
    broken = ctx.batch.flows.examples
    if broken and (lead is None or lead.failure_mode == "unfinished_work"):
        # Work that stopped partway names itself: "HDFS blocks stopping partway".
        kind = broken[0].kind
        named = ctx.system != "generic" and not kind.lower().startswith(ctx.system_name.lower())
        where = f" in {ctx.system_name}" if named else ""
        return clip(f"{ctx.severity.severity} · {kind}s stopping partway{where}", 140)
    if lead is not None:
        what = _sentence(_mode_words(lead.failure_mode))
    elif top is not None and top.score > 0:
        what = f"Suspected {_mode_words(top.failure_mode)}"
    elif features.error_events:
        # Named by the kind of trouble the error lines report most, so a list of incidents is not
        # a column of "Error spike".
        hits = {k: v for k, v in (features.issue_keyword_hits or {}).items() if k in _TROUBLE}
        what = _TROUBLE[max(hits, key=lambda k: hits[k])] if hits else "Error spike"
    elif signal_templates(ctx.batch):
        what = "New warnings"
    else:
        what = "Log anomaly check"
    if ctx.system == "generic":  # no named system: say what failed rather than "generic"
        component = lead.component if lead is not None else None
        where = ctx.service or component or next(iter(signal_components(ctx.batch, 1)), "")
    else:
        where = ctx.system_name + (f" ({ctx.service})" if ctx.service else "")
    place = f" in {where}" if where else ""
    affected = features.error_nodes or features.warn_nodes
    # "servers", as the console says everywhere else (RQ-m8).
    nodes = f" on {affected} servers" if affected > 1 else ""
    return clip(f"{ctx.severity.severity} · {what}{place}{nodes}", 140)


def _meaning(severity: Severity, features: WindowFeatures) -> str:
    """What a level means, without claiming errors the window does not have."""
    if severity is Severity.SEV3 and not features.error_events:
        return "Moderate: a contained problem with limited user impact."
    return SEVERITY_DESCRIPTIONS[severity]


def compose_draft(ctx: ReportContext) -> NarrativeOutput:
    features = ctx.batch.features
    sev = ctx.severity
    model_ev = ctx.find(EvidenceKind.MODEL, source="severity.model")
    rule_evs = ctx.all_of(EvidenceKind.RULE, source="severity.rules")
    window = ctx.find(EvidenceKind.FEATURE, source="parser", key="n_events")
    burst = ctx.find(EvidenceKind.FEATURE, source="parser", key="burst_score")
    spread = ctx.find(EvidenceKind.FEATURE, source="parser", key="error_nodes")
    warn_spread = ctx.find(EvidenceKind.FEATURE, source="parser", key="warn_nodes")
    floor_ev = next((e for e in rule_evs if e.data.get("effect") == "floor"), None)
    flows_ev = ctx.find(EvidenceKind.FEATURE, source="parser.flows", key="checked")
    flow_example = ctx.find(EvidenceKind.LOG, source="parser.flows", key="key")
    by_id = ctx.by_id
    signal = signal_templates(ctx.batch)

    summary: list[ClaimOut | None] = []
    p = sev.probabilities.get(sev.severity, 0.0)
    meaning = _meaning(sev.severity, features)
    how = DECIDED_BY_TEXT[sev.decided_by]
    if sev.set_empty and sev.decided_by == "fallback":
        how = (
            "No level was likely enough, so ARIA plans for the more serious of the model's most "
            "likely level and the rules' and a person decides"
        )
    # The model is skipped for a window far from its training data (the rules set the choices).
    unlike = model_ev is not None and bool(model_ev.data.get("outside_training"))
    if unlike:
        how = (
            "The calibrated model was not used, because this window is unlike the ones it "
            "learned from: the rules set the choices, and a person confirms"
        )
    # "SEV2 (high): major degradation ...", not "SEV2: High: major degradation ..." (J-p1).
    word, _, what = meaning.partition(": ")
    level = f"{sev.severity} ({word.lower()}): {what}" if what else f"{sev.severity}: {meaning}"
    severity_text = f"{level} {how}"
    if sev.decided_by in ("model", "llm", "fallback") and model_ev is not None:
        # Without the model the figure is a share of the rules' summed weight, not a chance.
        share = (
            f"{p:.0%} of the rules' weight" if unlike else f"the severity model gives it {p:.0%}"
        )
        severity_text += f" ({p:.0%})" if sev.decided_by == "model" else f" ({share})"
    if unlike and floor_ev is not None and sev.floor is not None:
        rule = floor_ev.title.split(": ", 1)[-1].rstrip(".")
        severity_text += f". A safety floor keeps it at {sev.floor} or worse: {rule}"
    model_top = max(sev.probabilities, key=sev.probabilities.__getitem__, default=sev.severity)
    if sev.decided_by == "rules" and floor_ev is not None and model_top != sev.severity:
        # A floor lifted the severity above the model's own view: say which, and what the model
        # thought, so a reviewer sees why the two disagree.
        rule = floor_ev.title.split(": ", 1)[-1].rstrip(".")
        severity_text = f"{level} Held there by a safety floor: {rule}"
        if model_ev is not None:
            severity_text += (
                f" (on its own, the severity model gave {model_top} "
                f"{sev.probabilities[model_top]:.0%})"
            )
    ticket_ev = ctx.find(EvidenceKind.MODEL, source="severity.ticket_model")
    if ticket_ev is not None and any(ticket_ev.id in c.evidence_ids for c in sev.rationale):
        # The ticket's own fields set this rating above what the logs show.
        severity_text = (
            f"{level} Raised to the ticket's "
            f"rating: the ticket model gives priority {ticket_ev.data.get('priority')} from its "
            "fields, above what the logs alone show, and a person confirms"
        )
        summary.append(_claim(f"{severity_text}.", ticket_ev, model_ev))
    else:
        summary.append(
            _claim(f"{severity_text}.", model_ev, floor_ev or (rule_evs[0] if rule_evs else None))
        )
    if window is not None and features.n_events:
        warnings = features.level_counts.get("WARN", 0)
        # Counted in the right number, and a window under a minute said so, not as "0.0 minutes".
        span = (
            f"over {features.duration_s / 60:.1f} minutes"
            if features.duration_s >= 60
            else "within a minute"
        )
        minutes = f"{_count(features.n_events, 'line')} {span}"
        if features.error_events:
            # "46 errors in 113 lines (40.7%), within a minute", not "46 errors (40.7% of 113
            # lines within a minute of logs)".
            scale = (
                f"{_count(features.error_events, 'error')} in "
                f"{_count(features.n_events, 'line')} ({features.error_ratio:.1%}), {span}"
                + (f", and {_count(warnings, 'warning')}" if warnings else "")
            )
        elif warnings:
            scale = f"No errors, but {_count(warnings, 'warning')}, in {minutes}"
        else:
            scale = f"No errors in {minutes}"
        if spread is not None:
            scale += f", on {features.error_nodes} of {features.distinct_nodes} servers"
        elif warn_spread is not None:
            scale += f", warnings on {features.warn_nodes} of {features.distinct_nodes} servers"
        summary.append(_claim(f"{scale}.", window, spread or warn_spread))
        if flows_ev is not None:
            example = f" For example, {flow_example.title}." if flow_example is not None else ""
            summary.append(_claim(f"{flows_ev.title}.{example}", flows_ev, flow_example))
        if not signal:
            quiet = (
                "No errors, and every warning matches a template already in this system's history."
                if warnings
                else "No error or warning lines in this window."
            )
            if flows_ev is not None:
                quiet += " The failure shows only as work that never finished."
            summary.append(_claim(quiet, window, flows_ev))
    if burst is not None and features.burst_score >= 2:
        summary.append(
            _claim(
                # The burst score is a z-score; the claim says what it means instead (J-m11).
                f"Errors peaked at {features.peak_errors_per_min:.0f} a minute, far more than "
                "in a typical minute of this window.",
                burst,
            )
        )
    top = next(((t, e) for t in signal if (e := _own_evidence(ctx, t)) is not None), None)
    if top is not None:
        template, template_ev = top
        kind = "error" if template.error_like else "new warning" if template.novel else "warning"
        on_nodes = f" on {_count(template.nodes, 'server')}" if template.nodes else ""
        real = _example(ctx, template)
        if real is not None:  # one real line reads better than the pattern it was mined into
            summary.append(
                _claim(
                    f"Most frequent {kind}, {_count(template.count, 'line')}{on_nodes}, like this one: "
                    f'"{clip(_quoted(real), 160)}".',
                    template_ev,
                    real,
                )
            )
        else:
            summary.append(
                _claim(
                    f'Most frequent {kind}: "{clip(plain_template(template.template), 160)}" '
                    f"({_count(template.count, 'line')}{on_nodes}).",
                    template_ev,
                )
            )
    # A rare line can decide an incident ("No space left on device"): it is said too, so the
    # summary does not stop at the most frequent one.
    serious = _most_serious(ctx, signal, top[0] if top is not None else None)
    if serious is not None:
        template, template_ev = serious
        real = _example(ctx, template)
        line = _quoted(real) if real is not None else plain_template(template.template)
        times = "once" if template.count == 1 else f"{template.count} times"
        summary.append(
            _claim(
                f'The most serious line, logged {times}: "{clip(line, 160)}".', template_ev, real
            )
        )
    incidents = [i for i in ctx.retrieval.incidents if i.evidence_id in by_id]
    # Retrieval may fall back to analogues on other systems; only this system's incidents can
    # suggest a cause.
    local = [i for i in incidents if i.system == ctx.batch.system]
    # Only a past incident on this system earns a line here: an analogue from another system is
    # listed under "Seen before", where it is marked as one, and suggests nothing on its own.
    if local:
        best = local[0]
        seen = f"seen {best.occurrences} times" if best.occurrences > 1 else "seen once"
        made = ", built from a sample" if best.source == "curated" else ""
        summary.append(
            _claim(
                f"Closest past incident{made}: {headline(best.title)}, {best.severity}, {seen}.",
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
            _claim(f"Errors span {features.node_spread:.0%} of the servers in this window.", spread)
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
        # The section is headed "Suspected cause", so the claim does not say it again.
        text = sentence_start(lead.statement.rstrip("."))
        if hyp_ev is not None and "confidence" in hyp_ev.data:
            # Quote the confidence only from the evidence that records it.
            text += f" (the investigation is {float(hyp_ev.data['confidence']):.0%} sure)"
        cause.append(_claim(f"{text}.", hyp_ev, *supporting[:4]))
    elif local and signal:
        best = local[0]
        agreeing = [i for i in local if i.failure_mode == best.failure_mode]
        which = "incident" if len(agreeing) == 1 else "incidents"
        cause.append(
            _claim(
                f"Likely {_mode_words(best.failure_mode)}: the closest past {which} on this "
                "system had this failure mode.",
                *[by_id[i.evidence_id or ""] for i in agreeing],
            )
        )

    actions: list[ActionOut] = []
    # A runbook for another system arrives with an analogue from that system; its steps would send
    # the reader to the wrong machinery, so only this system's runbooks and the generic one do.
    fitting = [
        ref
        for ref in ctx.retrieval.runbooks
        if (book := ctx.runbooks.get(ref.slug)) is not None
        and ("*" in book.systems or ctx.batch.system in book.systems)
    ]
    for ref in fitting[:2]:
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
        if sev.set_empty:
            p_top = sev.probabilities.get(sev.severity, 0.0)
            doubt = (
                f"no severity was likely enough to decide alone ({sev.severity} is the most "
                f"likely, at {p_top:.0%})"
            )
        elif len(sev.prediction_set) > 1:
            # Where the calibrated model sat out, the rules set the choices, as the summary says.
            judge = "the rules" if unlike else "the model"
            doubt = f"{judge} could not rule out {' or '.join(sev.prediction_set)}"
        else:
            p_set = sev.probabilities.get(sev.severity, 0.0)
            score = "the rules' score for" if unlike else "the model's confidence in"
            doubt = f"{score} {sev.severity} ({p_set:.0%}) is too low to decide alone"
        actions.insert(
            0,
            ActionOut(
                text=f"{CONFIRM_SEVERITY}: {doubt}.",
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
    if signal and (not local or ctx.retrieval.grade < 0.35):
        questions.append("No close match in incident memory. Is this a new failure mode?")
    if len(sev.prediction_set) > 1:
        questions.append(f"Is the impact closer to {' or '.join(sev.prediction_set)}?")
    if signal and lead is None and ctx.investigation.hypotheses:
        questions.append(
            "The investigation did not confirm a cause. What changed just before the errors began?"
        )

    return NarrativeOutput(
        title=compose_title(ctx),
        summary=_at_most(SUMMARY_LIMIT, [c for c in summary if c is not None], burst)
        or [_fallback_claim(ctx)],
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
    events: list[tuple[datetime, str, list[str]]] = []
    told: set[str] = set()  # log lines already quoted where their pattern begins
    for t in signal_templates(ctx.batch):
        if not t.first_ts or _own_evidence(ctx, t) is None:
            continue
        example = _example(ctx, t)
        if example is None:
            pattern = clip(plain_template(t.template), 100)
            events.append((t.first_ts, f'First "{pattern}" ({t.count} lines)', [t.evidence_id]))
            continue
        told.add(example.id)
        line = clip(_quoted(example), 100)
        text = (
            f'Logged once: "{line}"' if t.count == 1 else f'First of {t.count} lines like "{line}"'
        )
        events.append((t.first_ts, text, [t.evidence_id, example.id]))
    events.extend(
        (
            item.ts,
            (
                f"{'Warning' if item.data.get('level') == 'WARN' else 'Error'} logged: "
                f"{clip(_quoted(item), 120)}"
            ),
            [item.id],
        )
        for item in ctx.all_of(EvidenceKind.LOG, source="parser")
        if item.ts is not None and item.id not in told
    )
    events.extend(
        (item.ts, f"Alert fired: {clip(item.title, 120)}", [item.id])
        for item in ctx.all_of(EvidenceKind.ALERT)
        if item.ts is not None
    )
    seen: set[tuple[datetime, str]] = set()
    entries = []
    for ts, text, ids in sorted(events, key=lambda e: e[0]):
        if (ts, text) in seen:
            continue
        seen.add((ts, text))
        entries.append(TimelineEntry(ts=ts, text=text, evidence_ids=ids))
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
    "CONFIRM_SEVERITY",
    "DECIDED_BY_TEXT",
    "ReportContext",
    "compose_draft",
    "compose_timeline",
    "compose_title",
    "narrative_to_parts",
    "severity_rank_text",
]
