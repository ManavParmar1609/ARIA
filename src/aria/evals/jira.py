"""Ticket priority in public issue trackers: does ARIA's ticket model, trained on one company's
ServiceNow desk, agree with the priority people set on another organisation's tickets?

A subset of the Public Jira Dataset (Montgomery et al., MSR 2022): the first 20,000 issues of
Apache's and of Atlassian's own Jira in the dump's order (see ``aria.data.jira``). Each issue is
mapped onto the fields ARIA's ticket model reads when a ticket opens: its type as the category,
its first component as the subcategory, its project as the configuration item and its creation
time. Jira has no impact or urgency, so the model, never the impact x urgency matrix, decides.
Each instance's priority names are mapped onto ARIA's four levels by their written order, and
issues are split by creation time: the oldest 70% of each instance set the simple baselines, and
the newest 30% are scored. ARIA's model was trained only on the UCI ServiceNow log.

Measured per instance and pooled: accuracy and macro-F1 (mean of per-class F1), with bootstrap
95% intervals; urgent tickets (levels 1-2) rated 3 or 4, with an exact one-sided upper bound on
that miss rate; and how often the model's conformal set holds the true level. Baselines on the
same tickets: the priority the issue was opened with (from its change history), the commonest
level, and the commonest level for the issue's type. Nothing was tuned on this data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from aria.config import get_app_config
from aria.contracts.inputs import TicketContext
from aria.data import jira as data
from aria.evals import metrics as m
from aria.evals import ringc
from aria.severity.ticket import TicketModels

MISSING = {"missing": "download it with: aria data download --source jira-public"}
URGENT = {"1", "2"}
REFERENCE_SHARE = 0.7


def ticket_context(issue: data.Issue) -> TicketContext:
    """The issue as ARIA's ticket model reads a ticket when it opens."""
    return TicketContext(
        number=issue.key or None,
        category=issue.issue_type or None,
        subcategory=issue.components[0] if issue.components else None,
        cmdb_ci=issue.project or None,
        opened_at=issue.created,
    )


def split(issues: Sequence[data.Issue]) -> tuple[list[data.Issue], list[data.Issue]]:
    """(reference, test) per instance by creation time: the oldest 70% and the newest 30%."""
    reference: list[data.Issue] = []
    test: list[data.Issue] = []
    by_instance: dict[str, list[data.Issue]] = defaultdict(list)
    for issue in issues:
        if issue.level and issue.created is not None:
            by_instance[issue.instance].append(issue)
    for group in by_instance.values():
        group.sort(key=lambda i: (i.created, i.key))
        cut = int(len(group) * REFERENCE_SHARE)
        reference += group[:cut]
        test += group[cut:]
    return reference, test


def _scores(truth: Sequence[str], pred: Sequence[str]) -> dict[str, Any]:
    urgent = [p for t, p in zip(truth, pred, strict=True) if t in URGENT]
    missed = sum(1 for p in urgent if p not in URGENT)
    return {
        "accuracy": round(m.accuracy(truth, pred), 4),
        "accuracy_ci95": m.bootstrap(m.accuracy, truth, pred),
        "macro_f1": round(m.macro_f1(truth, pred), 4),
        "macro_f1_ci95": m.bootstrap(m.macro_f1, truth, pred),
        "urgent_missed": ringc.miss_rate(missed, len(urgent)),
        "predicted": dict(sorted(Counter(pred).items())),
    }


def score(
    models: TicketModels, reference: Sequence[data.Issue], test: Sequence[data.Issue]
) -> list[dict[str, Any]]:
    """One row per test issue with every method's level."""
    common: dict[str, str] = {}
    by_type: dict[tuple[str, str], str] = {}
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    type_counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for issue in reference:
        counts[issue.instance][issue.level or ""] += 1
        type_counts[(issue.instance, issue.issue_type)][issue.level or ""] += 1
    for instance, tally in counts.items():
        common[instance] = tally.most_common(1)[0][0]
    for key, tally in type_counts.items():
        by_type[key] = tally.most_common(1)[0][0]
    rows: list[dict[str, Any]] = []
    for issue in test:
        prediction = models.predict(ticket_context(issue))
        majority = common.get(issue.instance, "3")
        rows.append(
            {
                "instance": issue.instance,
                "key": issue.key,
                "project": issue.project,
                "issue_type": issue.issue_type,
                "created": issue.created.isoformat() if issue.created else None,
                "truth": issue.level,
                "priority": issue.priority,
                "aria": prediction.priority,
                "aria_model": prediction.model_priority,
                "decided_by": prediction.decided_by,
                "prediction_set": prediction.prediction_set,
                "at_open": issue.level_at_open or majority,
                "changed_after_open": issue.priority_at_open != issue.priority,
                "majority_class": majority,
                "by_issue_type": by_type.get((issue.instance, issue.issue_type), majority),
            }
        )
    return rows


METHODS = ("aria", "at_open", "majority_class", "by_issue_type")


def summarize(rows: Sequence[dict[str, Any]], *, reference: int = 0) -> dict[str, Any]:
    if not rows:
        return dict(MISSING)
    by_instance: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_instance[row["instance"]].append(row)

    def block(group: Sequence[dict[str, Any]]) -> dict[str, Any]:
        truth = [r["truth"] for r in group]
        return {
            "tickets": len(group),
            "levels": dict(sorted(Counter(truth).items())),
            "changed_after_open": ringc.share(
                sum(r["changed_after_open"] for r in group), len(group)
            ),
            "methods": {name: _scores(truth, [r[name] for r in group]) for name in METHODS},
            "set_coverage": round(m.set_coverage([r["prediction_set"] for r in group], truth), 4),
            "mean_set_size": round(
                sum(len(r["prediction_set"]) for r in group) / max(1, len(group)), 3
            ),
        }

    return {
        "source": "the Public Jira Dataset (Apache's and Atlassian's Jira)",
        "citation": data.JIRA_CITATION,
        "stamp": ringc.STAMP,
        "reference_tickets": reference,
        "test_tickets": len(rows),
        "instances": {k: block(v) for k, v in sorted(by_instance.items())},
        "pooled": block(rows),
        "decided_by": dict(Counter(r["decided_by"] for r in rows)),
        "projects": dict(Counter(r["project"] for r in rows).most_common(10)),
    }


def evaluate(
    root: Path = data.JIRA_DIR, model_file: Path | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(summary, rows) for the downloaded subset, or why there is none."""
    issues = data.read_issues(root)
    if not issues:
        return dict(MISSING), []
    path = model_file or Path(get_app_config().severity.ticket_model_file)
    if not path.exists():
        return {"missing": "train the ticket model with: aria train tickets"}, []
    reference, test = split(issues)
    rows = score(TicketModels.load(path), reference, test)
    summary = summarize(rows, reference=len(reference))
    summary["issues_read"] = len(issues)
    summary["without_level"] = sum(1 for i in issues if not i.level)
    return summary, rows
