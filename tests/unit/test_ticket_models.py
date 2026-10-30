"""Ticket priority and SLA models.

The UCI dataset is not in the test fixtures, so these tests use SYNTHETIC tickets generated
here with a known priority matrix. They check the mechanics (encoding, splits, calibration,
persistence), not real-world accuracy.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from aria.contracts.base import Severity
from aria.contracts.inputs import TicketContext
from aria.severity.ticket import TicketEncoder, TicketModels, fit_ticket_models, learn_matrix, level

MATRIX = {
    ("1", "1"): "1",
    ("1", "2"): "2",
    ("2", "1"): "2",
    ("2", "2"): "3",
    ("1", "3"): "3",
    ("3", "1"): "3",
    ("2", "3"): "4",
    ("3", "2"): "4",
    ("3", "3"): "4",
}


def synthetic_tickets(n: int = 1_500, seed: int = 0) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    start = datetime(2016, 3, 1, tzinfo=UTC)
    rows = []
    for i in range(n):
        impact, urgency = rng.choice("123"), rng.choice("123")
        priority = MATRIX[(impact, urgency)]
        category = rng.choice(["Category 26", "Category 53", "Category 9"])
        if category == "Category 9" and rng.random() < 0.5:  # a category often escalated
            priority = str(max(1, int(priority) - 1))
        breach = rng.random() < (0.6 if priority in "12" else 0.15)
        fraction = i / n
        rows.append(
            {
                "number": f"INC{i:07d}",
                "opened_at": start + timedelta(hours=i),
                "category": category,
                "subcategory": rng.choice(["Subcategory 174", "Subcategory 170"]),
                "symptom": rng.choice(["Symptom 491", "Symptom 232", None]),
                "contact_type": "Phone",
                "location": rng.choice(["Location 143", "Location 204"]),
                "first_assignment_group": rng.choice(["Group 70", "Group 24"]),
                "impact": f"{impact} - x",
                "urgency": f"{urgency} - x",
                "priority": f"{priority} - x",
                "knowledge": rng.random() < 0.2,
                "priority_confirmation": rng.random() < 0.5,
                "made_sla": not breach,
                "split": "train" if fraction < 0.7 else "calib" if fraction < 0.85 else "test",
            }
        )
    return rows


def test_level_parses_uci_values() -> None:
    assert level("2 - High") == "2"
    assert level(None) is None
    assert level("?") is None


def test_matrix_is_learned_from_data() -> None:
    rows = [
        {"impact": i, "urgency": u, "priority": p} for (i, u), p in MATRIX.items() for _ in range(6)
    ]
    assert learn_matrix(rows)["1|1"] == "1"
    assert learn_matrix(rows)["3|3"] == "4"
    assert learn_matrix(rows[:3]) == {}  # too few votes


def test_encoder_folds_rare_and_missing_values() -> None:
    encoder = TicketEncoder.fit([{"category": "A"}] * 25 + [{"category": "B"}] * 3, min_count=20)
    assert encoder.vocab["category"] == ["A"]
    assert encoder.row({"category": "B"})["category=other"] == 1.0
    assert encoder.row({"category": "?"})["category=missing"] == 1.0


def test_models_learn_priority_and_sla_risk(tmp_path: Path) -> None:
    models, report = fit_ticket_models(synthetic_tickets(), alpha=0.1)
    assert report["priority"]["conformal_split"]["coverage"] >= 0.85
    critical = TicketContext(category="Category 26", impact="1 - High", urgency="1 - High")
    low = TicketContext(category="Category 26", impact="3 - Low", urgency="3 - Low")
    p_critical, p_low = models.predict(critical), models.predict(low)
    assert p_critical.severity is Severity.SEV1
    assert p_critical.matrix_priority == "1"
    assert p_low.severity is Severity.SEV4
    assert p_critical.sla_breach_risk is not None
    assert p_low.sla_breach_risk is not None
    assert p_critical.sla_breach_risk > p_low.sla_breach_risk
    path = tmp_path / "ticket.json"
    models.save(path)
    loaded = TicketModels.load(path)
    assert loaded.predict(critical) == p_critical


def test_training_needs_labelled_tickets() -> None:
    with pytest.raises(ValueError, match="no training tickets"):
        fit_ticket_models([{"priority": None, "split": "train"}])


def test_the_matrix_decides_a_known_pair_and_the_model_the_rest() -> None:
    models, _ = fit_ticket_models(synthetic_tickets(), alpha=0.1)
    known = models.predict(TicketContext(category="Category 9", impact="2 - x", urgency="2 - x"))
    assert known.decided_by == "matrix"
    assert known.priority == known.matrix_priority == "3"
    assert known.priority in known.prediction_set
    unknown = models.predict(TicketContext(category="Category 9", impact=None, urgency="2 - x"))
    assert unknown.decided_by == "model"
    assert unknown.matrix_priority is None
    assert unknown.priority == unknown.model_priority


def test_the_model_can_express_the_impact_urgency_matrix() -> None:
    # Additive one-hot impact and urgency cannot express the matrix; the pair feature can.
    models, _ = fit_ticket_models(synthetic_tickets(), alpha=0.1)
    agree = [
        models.predict(TicketContext(category="Category 26", impact=f"{i} - x", urgency=f"{u} - x"))
        for (i, u) in MATRIX
    ]
    assert sum(p.model_priority == MATRIX[k] for p, k in zip(agree, MATRIX, strict=True)) >= 8


def _write_uci_log(path: Path, rows: list[dict[str, Any]]) -> None:
    """One audit event per ticket, in the UCI CSV's own format."""
    import csv

    from aria.data.uci import UCI_COLUMNS

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=UCI_COLUMNS)
        writer.writeheader()
        for row in rows:
            opened = row["opened_at"].strftime("%d/%m/%Y %H:%M")
            event = dict.fromkeys(UCI_COLUMNS, "?")
            event.update(
                number=row["number"],
                incident_state="Closed",
                active="false",
                reassignment_count="0",
                reopen_count="0",
                sys_mod_count="1",
                made_sla="true" if row["made_sla"] else "false",
                opened_at=opened,
                sys_updated_at=opened,
                contact_type=row["contact_type"],
                location=row["location"],
                category=row["category"],
                subcategory=row["subcategory"],
                u_symptom=row["symptom"] or "?",
                impact=row["impact"],
                urgency=row["urgency"],
                priority=row["priority"],
                assignment_group=row["first_assignment_group"],
                knowledge="true" if row["knowledge"] else "false",
                u_priority_confirmation="true" if row["priority_confirmation"] else "false",
            )
            writer.writerow(event)


def test_the_real_ticket_evaluation_scores_the_newest_tickets(tmp_path: Path) -> None:
    import dataclasses

    from aria.data.uci import aggregate, iter_events
    from aria.evals.tickets import evaluate_uci, summarize

    _write_uci_log(tmp_path / "incident_event_log.csv", synthetic_tickets())
    rows = [
        dataclasses.asdict(s) for s in aggregate(iter_events(tmp_path / "incident_event_log.csv"))
    ]
    models, _ = fit_ticket_models([r for r in rows if r["split"] != "test"], alpha=0.1)
    result = evaluate_uci(models, tmp_path)
    assert result["test"] == sum(r["split"] == "test" for r in rows)
    aria, alone = result["priority"]["aria"], result["priority"]["model_only"]
    assert aria["accuracy"] >= result["priority"]["majority_class"]["accuracy"]
    assert aria["accuracy"] >= alone["accuracy"] - 0.05
    assert result["decided_by_matrix"] == 1.0
    assert result["sla"]["auroc"] > 0.6  # breaches follow priority in the synthetic tickets
    assert result["conformal"]["coverage"] >= 0.8

    from aria.evals.report import _tickets, _tickets_summary

    text = "\n".join(_tickets(result))
    assert "## Real tickets, a ServiceNow service desk" in text
    assert "| ARIA's SLA model |" in text
    assert "Real tickets" in "\n".join(_tickets_summary(result))
    assert _tickets_summary({"missing": "x"}) == []

    # A model trained on other tickets is reported as stale rather than scored.
    stale, _ = fit_ticket_models(synthetic_tickets(seed=1)[:900], alpha=0.1)
    assert "stale" in evaluate_uci(stale, tmp_path)
    assert "missing" in summarize(tmp_path / "no-model.json", tmp_path)
    assert "missing" in summarize(tmp_path / "no-model.json", tmp_path / "nothing")
