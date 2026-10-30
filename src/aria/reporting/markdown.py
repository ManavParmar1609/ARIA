"""Markdown renderings of a report: the incident report itself, and a postmortem skeleton."""

from __future__ import annotations

from aria.contracts.base import Claim
from aria.contracts.report import IncidentReport
from aria.reporting.writer import cited_evidence

# Report text quotes log lines, which anyone can write. The exports are pasted into other tools,
# so HTML, links, images and chat mentions (<!channel>) in that text must stay inert text, and so
# must emphasis and code marks: a template's "<*>" must not turn the text after it italic.
_INERT = str.maketrans(
    {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "[": "\\[",
        "]": "\\]",
        "*": "\\*",
        "_": "\\_",
        "`": "\\`",
    }
)


def _safe(text: str) -> str:
    return text.translate(_INERT)


def _cite(ids: list[str]) -> str:
    return "".join(f"[{e}]" for e in ids)


def _claims(claims: list[Claim]) -> list[str]:
    return [f"- {_safe(c.text)} {_cite(c.evidence_ids)}" for c in claims] or ["- _None._"]


def _cell(text: str) -> str:
    return " ".join(_safe(text).replace("|", "\\|").split())


def render_markdown(report: IncidentReport, *, decided_by: str | None = None) -> str:
    lines = [f"# {_safe(report.title)}", ""]
    meta = [
        f"**Severity:** {report.severity}",
        f"**Status:** {report.status}",
        f"**Run:** `{report.run_id}`",
    ]
    if decided_by:
        meta.insert(1, f"**Decided by:** {decided_by}")
    # The offline fake stands in for a model without keys: what it writes is the template.
    offline = report.generated_by == "template" or (report.model or "").startswith("fake/")
    source = "ARIA's evidence template (no LLM)" if offline else f"LLM ({report.model})"
    meta.append(f"**Written by:** {source}")
    lines += [" · ".join(meta), ""]

    lines += ["## Summary", *_claims(report.summary), ""]
    if report.impact:
        lines += ["## Impact", *_claims(report.impact), ""]
    if report.suspected_cause:
        lines += ["## Suspected cause", *_claims(report.suspected_cause), ""]
    if report.timeline:
        lines += ["## Timeline", "", "| Time (UTC) | Event | Evidence |", "|---|---|---|"]
        for entry in report.timeline:
            when = entry.ts.strftime("%Y-%m-%d %H:%M:%S") if entry.ts else "-"
            lines.append(f"| {when} | {_cell(entry.text)} | {_cite(entry.evidence_ids)} |")
        lines.append("")
    if report.similar_incidents:
        lines += [
            "## Similar past incidents",
            "",
            "| Incident | Severity | Seen | Resolution | Evidence |",
            "|---|---|---|---|---|",
        ]
        for inc in report.similar_incidents:
            label = f"{inc.title}{' (synthetic history)' if inc.source == 'curated' else ''}"
            seen = f"{inc.occurrences}x" + (
                f", last {inc.last_seen:%Y-%m-%d}" if inc.last_seen else ""
            )
            lines.append(
                f"| {_cell(label)} | {inc.severity} | {seen} | {_cell(inc.resolution[:200])} | {_cite([inc.evidence_id] if inc.evidence_id else [])} |"
            )
        lines.append("")
    if report.ticket_history is not None:
        t = report.ticket_history
        breach = f"{t.sla_breach_rate:.0%}" if t.sla_breach_rate is not None else "n/a"
        lines += [
            "## ITSM ticket history",
            "",
            (
                f"- {t.n_similar} similar tickets (matched on {t.matched_on or 'all tickets'}); "
                f"SLA breached in {breach}; median resolution {t.median_resolution_hours} h. "
                f"{_cite([t.evidence_id] if t.evidence_id else [])}"
            ),
            "",
        ]
    if report.actions:
        lines += ["## Recommended actions", ""]
        for action in report.actions:
            risk = f"risk: {action.risk}" + (", needs approval" if action.risk != "low" else "")
            runbook = f" · runbook `{action.runbook_slug}`" if action.runbook_slug else ""
            lines.append(
                f"- [ ] {_safe(action.text)} ({risk}{runbook}) {_cite(action.evidence_ids)}"
            )
        lines.append("")
    if report.open_questions:
        lines += ["## Open questions", *[f"- {_safe(q)}" for q in report.open_questions], ""]

    cited = cited_evidence(report)
    if cited:
        lines += ["## Evidence", "", "| ID | Kind | Source | Detail |", "|---|---|---|---|"]
        lines += [f"| {e.id} | {e.kind} | `{e.source}` | {_cell(e.title)} |" for e in cited]
        lines.append("")
    v = report.validation
    errors = len(v.errors)
    lines.append(
        f"_Validation: {'passed' if v.ok else 'FAILED'} · {v.checked_claims} statements checked · "
        f"citation coverage {v.citation_coverage:.0%} · {errors} errors._"
    )
    if any(inc.source == "curated" for inc in report.similar_incidents):
        lines.append(
            "_Similar incidents marked synthetic come from ARIA's seeded, semi-synthetic history._"
        )
    return "\n".join(lines) + "\n"


def render_postmortem(report: IncidentReport) -> str:
    """A blameless postmortem skeleton pre-filled from the report; people write the rest."""
    todo = "_To be completed by the incident team._"
    lines = [
        f"# Postmortem: {_safe(report.title)}",
        "",
        f"**Severity:** {report.severity} · **Report:** `{report.report_id}` · **Run:** `{report.run_id}`",
        "",
        "## Summary",
        *_claims(report.summary),
        "",
        "## Impact",
        *(_claims(report.impact) if report.impact else [todo]),
        "",
        "## Timeline",
    ]
    lines += [
        f"- {e.ts:%Y-%m-%d %H:%M} UTC: {_safe(e.text)} {_cite(e.evidence_ids)}"
        for e in report.timeline
        if e.ts
    ] or [todo]
    lines += [
        "",
        "## Root cause",
        *(_claims(report.suspected_cause) if report.suspected_cause else [todo]),
        "",
        "_ARIA's suspected cause is a hypothesis; confirm or correct it here._",
        "",
        "## What went well",
        todo,
        "",
        "## What could have gone better",
        todo,
        "",
        "## Action items",
        "",
        "| Action | Owner | Due | Risk |",
        "|---|---|---|---|",
    ]
    lines += [f"| {_cell(a.text)} | | | {a.risk} |" for a in report.actions] or ["| | | | |"]
    return "\n".join(lines) + "\n"
