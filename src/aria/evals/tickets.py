"""Ticket triage on a real ITSM log: priority and SLA breach risk when a ticket opens.

UCI "Incident management process enriched event log" (Amaral et al. 2018): the ServiceNow audit
trail of an IT company's service desk. ARIA aggregates each incident's events, keeps only the
fields known when it opened, and splits by open time: the oldest 70% train the models, the next
15% calibrate them, and the newest 15% are scored here. The model scored is the file `make train`
writes (``models/severity_ticket.json``); its training size is checked against the split, so a
stale file is reported rather than scored.

Priority: ARIA's decision (the impact x urgency matrix learned from training tickets, the model
where the matrix has no entry), the model alone, the priority the ticket opened with, and the
commonest priority. Severe tickets (priority 1 or 2) rated 3 or 4 are counted, and so are tickets
escalated after they opened, which nothing known at open can foresee. SLA: the model's breach
risk against each single field's breach rate in training, by AUROC with a bootstrap 95% interval,
and the Brier score against always predicting the base rate.
"""

from __future__ import annotations

import dataclasses
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import brier_score_loss, roc_auc_score

from aria.contracts.inputs import TicketContext
from aria.data.uci import aggregate, find_event_log, iter_events
from aria.evals import metrics as m
from aria.severity.ticket import TicketModels, level

UCI_DIR = Path("data/raw/uci-incidents")
UCI_CITATION = (
    "C. Amaral, M. Fantinato, H. Reijers, S. Peres. Enhancing Completion Time Prediction Through "
    "Attribute Selection. 2018. UCI Machine Learning Repository, DOI 10.24432/C57S4H."
)
SEVERE = {"1", "2"}
# Fields whose training breach rate is a one-field baseline for the SLA model.
SLA_BASELINE_FIELDS = ("first_assignment_group", "category", "location", "priority_at_open")
_SMOOTHING = 20  # tickets of prior weight, so a rare value's rate leans on the base rate


def ticket_context(row: Mapping[str, Any]) -> TicketContext:
    """The ticket as it stood when it opened, from an aggregated incident."""
    return TicketContext(
        number=row.get("number"),
        category=row.get("category"),
        subcategory=row.get("subcategory"),
        symptom=row.get("symptom"),
        cmdb_ci=row.get("cmdb_ci"),
        contact_type=row.get("contact_type"),
        location=row.get("location"),
        assignment_group=row.get("first_assignment_group"),
        impact=row.get("impact"),
        urgency=row.get("urgency"),
        opened_at=row.get("opened_at"),
        knowledge=row.get("knowledge"),
        priority_confirmation=row.get("priority_confirmation"),
    )


def _rate_by(
    field: str, train: Sequence[Mapping[str, Any]]
) -> Callable[[Mapping[str, Any]], float]:
    counts: dict[Any, list[int]] = defaultdict(lambda: [0, 0])
    for row in train:
        counts[row.get(field)][0] += 0 if row["made_sla"] else 1
        counts[row.get(field)][1] += 1
    base = sum(b for b, _ in counts.values()) / max(1, sum(n for _, n in counts.values()))

    def rate(row: Mapping[str, Any]) -> float:
        breaches, n = counts.get(row.get(field), (0, 0))
        return (breaches + base * _SMOOTHING) / (n + _SMOOTHING)

    return rate


def _auroc(truth: Sequence[int], scores: Sequence[float]) -> float:
    return float(roc_auc_score(truth, scores)) if len(set(truth)) == 2 else 0.5


def _priority(truth: Sequence[str], pred: Sequence[str]) -> dict[str, Any]:
    severe = [p for t, p in zip(truth, pred, strict=True) if t in SEVERE]
    return {
        "accuracy": round(m.accuracy(truth, pred), 4),
        "accuracy_ci95": m.bootstrap(m.accuracy, truth, pred),
        "macro_f1": round(m.macro_f1(truth, pred), 4),
        "severe_missed": sum(1 for p in severe if p not in SEVERE),
    }


def evaluate_uci(models: TicketModels, uci_dir: Path = UCI_DIR) -> dict[str, Any]:
    path = find_event_log(uci_dir)
    if path is None:
        return {"missing": "download it with: aria data download --source uci-incidents"}
    rows = [dataclasses.asdict(s) for s in aggregate(iter_events(path))]
    train = [r for r in rows if r["split"] == "train"]
    trained_on = (models.metadata.get("n") or {}).get("train")
    if trained_on != len(train):
        return {
            "stale": f"the ticket model trained on {trained_on} tickets, but this log's training "
            f"split has {len(train)}; retrain it with: aria train tickets"
        }
    test = [r for r in rows if r["split"] == "test" and level(r["priority"])]
    preds = [models.predict(ticket_context(r)) for r in test]
    truth = [level(r["priority"]) or "" for r in test]
    majority = Counter(level(r["priority"]) for r in train if level(r["priority"])).most_common(1)
    common = str(majority[0][0]) if majority else "3"
    methods = {
        "aria": [p.priority for p in preds],
        "model_only": [p.model_priority for p in preds],
        "priority_at_open": [level(r["priority_at_open"]) or common for r in test],
        "majority_class": [common] * len(test),
    }
    # Priority levels are single digits, so "1" < "3" reads as "more severe than".
    escalated = [
        (p, r)
        for p, r, t in zip(preds, test, truth, strict=True)
        if level(r["priority_at_open"]) and t < str(level(r["priority_at_open"]))
    ]

    sla_rows = [(p, r) for p, r in zip(preds, test, strict=True) if r["made_sla"] is not None]
    breach = [0 if r["made_sla"] else 1 for _, r in sla_rows]
    risk = [p.sla_breach_risk or 0.0 for p, _ in sla_rows]
    base_rate = float(
        np.mean([0 if r["made_sla"] else 1 for r in train if r["made_sla"] is not None])
    )
    baselines = {}
    for field in SLA_BASELINE_FIELDS:
        rate = _rate_by(field, [r for r in train if r["made_sla"] is not None])
        baselines[field] = round(_auroc(breach, [rate(r) for _, r in sla_rows]), 4)

    return {
        "source": "UCI incident management process enriched event log (ServiceNow)",
        "citation": UCI_CITATION,
        "model_version": models.version,
        "events": sum(r["n_events"] for r in rows),
        "incidents": len(rows),
        "opened_from": min(r["opened_at"] for r in rows if r["opened_at"]).date().isoformat(),
        "opened_to": max(r["opened_at"] for r in rows if r["opened_at"]).date().isoformat(),
        "split": {s: sum(1 for r in rows if r["split"] == s) for s in ("train", "calib", "test")},
        "test": len(test),
        "test_by_priority": {c: truth.count(c) for c in sorted(set(truth))},
        "decided_by_matrix": round(
            sum(1 for p in preds if p.decided_by == "matrix") / max(1, len(preds)), 4
        ),
        "priority": {name: _priority(truth, pred) for name, pred in methods.items()},
        "same_as_at_open": round(
            float(
                np.mean(
                    [t == level(r["priority_at_open"]) for t, r in zip(truth, test, strict=True)]
                )
            ),
            4,
        ),
        "escalated": {
            "tickets": len(escalated),
            "foreseen": sum(
                1 for p, r in escalated if str(p.priority) < str(level(r["priority_at_open"]))
            ),
        },
        "conformal": {
            "target_coverage": round(1 - models.priority.alpha, 4),
            "coverage": round(m.set_coverage([p.prediction_set for p in preds], truth), 4),
            "mean_set_size": round(float(np.mean([len(p.prediction_set) for p in preds])), 3),
        },
        "sla": {
            "n": len(sla_rows),
            "breach_rate": round(float(np.mean(breach)), 4) if breach else 0.0,
            "auroc": round(_auroc(breach, risk), 4),
            "auroc_ci95": m.bootstrap(_auroc, breach, risk),
            "brier": round(float(brier_score_loss(breach, risk)), 4),
            "brier_base_rate": round(float(brier_score_loss(breach, [base_rate] * len(breach))), 4),
            "ece": round(
                m.expected_calibration_error(
                    [{"breach": r, "met": 1 - r} for r in risk],
                    ["breach" if b else "met" for b in breach],
                ),
                4,
            ),
            "baselines_auroc": baselines,
        },
    }


def summarize(model_file: Path, uci_dir: Path = UCI_DIR) -> dict[str, Any]:
    """The UCI ticket results, or why there are none."""
    if find_event_log(uci_dir) is None:
        return {"missing": "download it with: aria data download --source uci-incidents"}
    if not model_file.exists():
        return {"missing": "train the ticket model with: aria train tickets"}
    return evaluate_uci(TicketModels.load(model_file), uci_dir)
