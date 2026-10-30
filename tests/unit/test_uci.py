"""UCI loader tests.

The fixture rows below are SYNTHETIC: they copy the UCI file's column layout and value formats so
the parser and aggregation logic can be tested offline. They are not UCI data.
"""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aria.data.uci import UCI_COLUMNS, aggregate, iter_events, parse_event


def _row(**overrides: str) -> dict[str, str]:
    row = dict.fromkeys(UCI_COLUMNS, "?")
    row.update(
        {
            "incident_state": "New",
            "active": "true",
            "reassignment_count": "0",
            "reopen_count": "0",
            "sys_mod_count": "0",
            "made_sla": "true",
            "opened_at": "29/2/2016 01:16",
            "sys_updated_at": "29/2/2016 01:23",
            "contact_type": "Phone",
            "location": "Location 143",
            "category": "Category 55",
            "subcategory": "Subcategory 170",
            "u_symptom": "Symptom 72",
            "impact": "2 - Medium",
            "urgency": "2 - Medium",
            "priority": "3 - Moderate",
            "assignment_group": "Group 56",
            "knowledge": "true",
            "u_priority_confirmation": "false",
            "notify": "Do Not Notify",
        }
    )
    row.update(overrides)
    return row


def test_parse_event_types_values_and_maps_question_marks_to_none() -> None:
    event = parse_event(_row(number="INC0000045", resolved_at="?"))
    assert event["opened_at"] == datetime(2016, 2, 29, 1, 16, tzinfo=UTC)
    assert event["made_sla"] is True
    assert event["reassignment_count"] == 0
    assert event["resolved_at"] is None
    assert event["category"] == "Category 55"


def test_parse_event_rejects_schema_drift() -> None:
    row = _row(number="INC1")
    row["new_column"] = "x"
    with pytest.raises(ValueError, match="unexpected UCI columns"):
        parse_event(row)


def test_aggregate_uses_first_event_for_inputs_and_last_for_outcomes() -> None:
    events = [
        parse_event(
            _row(
                number="INC1",
                sys_mod_count="0",
                priority="3 - Moderate",
                assignment_group="Group 1",
            )
        ),
        parse_event(
            _row(
                number="INC1",
                sys_mod_count="1",
                reassignment_count="2",
                sys_updated_at="29/2/2016 05:00",
                assignment_group="Group 2",
            )
        ),
        parse_event(
            _row(
                number="INC1",
                sys_mod_count="2",
                incident_state="Resolved",
                priority="2 - High",
                made_sla="false",
                reopen_count="1",
                resolved_at="29/2/2016 11:16",
                closed_code="code 5",
                sys_updated_at="29/2/2016 11:20",
                assignment_group="Group 2",
            )
        ),
    ]
    [incident] = aggregate(events)
    assert incident.priority_at_open == "3 - Moderate"
    assert incident.priority == "2 - High"
    assert incident.first_assignment_group == "Group 1"
    assert incident.final_assignment_group == "Group 2"
    assert incident.made_sla is False
    assert incident.reopen_count == 1
    assert incident.reassignment_count == 2
    assert incident.resolution_hours == pytest.approx(10.0)
    assert incident.n_events == 3


def test_time_split_never_puts_older_incidents_in_test() -> None:
    events = [
        parse_event(_row(number=f"INC{i:03d}", opened_at=f"{1 + i % 28}/{1 + i // 28}/2016 08:00"))
        for i in range(100)
    ]
    incidents = aggregate(events)
    latest_train = max(i.opened_at for i in incidents if i.split == "train" and i.opened_at)
    earliest_test = min(i.opened_at for i in incidents if i.split == "test" and i.opened_at)
    assert latest_train <= earliest_test
    assert {i.split for i in incidents} == {"train", "calib", "test"}


def test_iter_events_reads_a_csv(tmp_path: Path) -> None:
    path = tmp_path / "incident_event_log.csv"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=UCI_COLUMNS)
        writer.writeheader()
        writer.writerow(_row(number="INC9"))
    [event] = list(iter_events(path))
    assert event["number"] == "INC9"
