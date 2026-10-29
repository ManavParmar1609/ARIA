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
