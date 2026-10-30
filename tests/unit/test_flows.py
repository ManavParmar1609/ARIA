"""Units of work that started but never finished (parsing/flows.py)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from aria.config import GuardrailConfig
from aria.contracts import EvidenceKind
from aria.evidence import EvidenceStore
from aria.parsing.flows import (
    Step,
    check_flows,
    group_units,
    load_flow_settings,
    pair_groups,
    short_step,
)
from aria.parsing.parser import parse_lines

T0 = datetime(2008, 11, 9, 20, 35, tzinfo=UTC)
NAMES = {"start": "allocate <*>", "copy": "Receiving block <*>", "done": "Received block <*>"}


def _unit(block: int, at: float, copies: int = 3, done: int | None = None) -> list[Step]:
    """One block's life: allocated, copied to ``copies`` nodes, ``done`` of them confirmed."""
    done = copies if done is None else done
    steps = [("start", 0.0)] + [("copy", 0.5)] * copies + [("done", 2.0)] * done
    return [
        Step(0, T0 + timedelta(seconds=at + dt), kind, NAMES[kind], f"{kind} blk_{block}")
        for kind, dt in steps
    ]


def _window(*units: list[Step]) -> list[Step]:
    steps = sorted((s for unit in units for s in unit), key=lambda s: s.ts or T0)
    return [dataclasses.replace(s, idx=i) for i, s in enumerate(steps)]


def _healthy(n: int, *, every: float = 10.0, copies: int = 3) -> list[list[Step]]:
    return [_unit(i, 30 + i * every, copies) for i in range(n)]


def test_units_whose_steps_all_arrive_are_not_flagged() -> None:
    result = check_flows(_window(*_healthy(120)))
    assert result.units == {"HDFS block": 120}
    assert result.n_checked > 0
    assert result.broken == []
    assert {(p.a, p.b) for p in result.pairs} == {("copy", "done")}


def test_a_unit_missing_a_step_is_flagged_with_a_readable_reason() -> None:
    broken = [_unit(900 + i, 400 + i * 10, copies=3, done=2) for i in range(3)]
    result = check_flows(_window(*_healthy(120), *broken))
    assert sorted(b.key for b in result.broken) == ["blk_900", "blk_901", "blk_902"]
    finding = result.broken[0]
    assert finding.problem == "mismatch"
    assert finding.reason == "3 × “Receiving block …” but 2 × “Received block …”"
    assert finding.steps == ("copy", "done")
    assert result.broken_ratio == round(3 / result.n_checked, 4)


def test_a_rare_step_is_flagged_even_when_the_counts_add_up() -> None:
    odd = _unit(999, 600)
    odd.append(Step(0, T0 + timedelta(seconds=603), "retry", "Retrying block <*>", "blk_999"))
    result = check_flows(_window(*_healthy(300, every=4), odd))
    assert [(b.key, b.problem) for b in result.broken] == [("blk_999", "unusual_step")]
    assert "“Retrying block …”" in result.broken[0].reason


def test_units_cut_off_by_either_end_of_the_window_are_not_judged() -> None:
    late = _unit(800, 30 + 120 * 10 - 1, copies=3, done=0)  # its confirmations never arrive
    early = _unit(801, 0.0, copies=3, done=3)[1:]  # began before the window opened
    result = check_flows(_window(*_healthy(120), late, early))
    assert "blk_800" not in result.checked_keys
    assert "blk_801" not in result.checked_keys
    assert result.broken == []


def test_a_window_with_too_few_units_is_not_checked() -> None:
    result = check_flows(_window(*_healthy(10), _unit(77, 200, done=0)))
    assert result.units == {"HDFS block": 11}
    assert result.n_checked == 0
    assert result.broken == []


def test_untimed_lines_are_checked_without_settle_margins() -> None:
    steps = [dataclasses.replace(s, ts=None) for s in _window(*_healthy(60), _unit(5, 0, done=1))]
    result = check_flows(steps)
    assert result.settle_s == {}
    assert [b.key for b in result.broken] == ["blk_5"]


def test_a_line_that_names_several_units_counts_for_each() -> None:
    line = Step(0, T0, "ask", "ask <*> to replicate <*>", "ask blk_1 and blk_2 to replicate")
    units = group_units([line], load_flow_settings().kinds)["hdfs_block"]
    assert sorted(units) == ["blk_1", "blk_2"]
    assert all(u.counts == {"ask": 1} for u in units.values())


def test_pairs_merge_into_one_lifecycle_and_steps_read_as_text() -> None:
    result = check_flows(_window(*[_unit(i, 30 + i * 10) for i in range(120)]))
    assert pair_groups(result.pairs) == [("HDFS block", ["copy", "done"])]
    assert short_step("Receiving block <*> src: <*>") == "Receiving block … src: …"
    assert short_step("x" * 80, limit=10) == "xxxxxxxxx…"


@settings(max_examples=25, deadline=None)
@given(st.lists(st.integers(min_value=1, max_value=6), min_size=40, max_size=90))
def test_complete_units_are_never_flagged_whatever_their_replication(copies: list[int]) -> None:
    window = _window(*[_unit(i, 30 + i * 10, c) for i, c in enumerate(copies)])
    assert check_flows(window).broken == []


def _hdfs_lines(blocks: int, broken: set[int]) -> list[str]:
    lines = []
    for b in range(blocks):
        at = T0 + timedelta(seconds=30 + b * 6)
        stamp = f"{at:%y%m%d %H%M%S}"
        lines.append(
            f"{stamp} 35 INFO dfs.FSNamesystem: BLOCK* NameSystem.allocateBlock: /tmp/f{b}. blk_{b}"
        )
        for node in range(3):
            lines.append(
                f"{stamp} 143 INFO dfs.DataNode$DataXceiver: Receiving block blk_{b} "
                f"src: /10.0.0.{node}:5{node}000 dest: /10.0.0.{node}:50010"
            )
        done = 2 if b in broken else 3
        later = f"{at + timedelta(seconds=2):%y%m%d %H%M%S}"
        for node in range(done):
            lines.append(
                f"{later} 145 INFO dfs.DataNode$PacketResponder: Received block blk_{b} "
                f"of size 67108864 from /10.0.0.{node}"
            )
    return lines


def test_the_parser_turns_broken_units_into_features_and_cited_evidence() -> None:
    evidence = EvidenceStore()
    out = parse_lines(
        _hdfs_lines(150, broken={70, 71, 72, 73}),
        system="hdfs",
        guard=GuardrailConfig(),
        evidence=evidence,
    )
    features, flows = out.batch.features, out.batch.flows
    assert features.broken_flows == 4
    assert features.flows_checked == flows.checked["HDFS block"]
    assert features.broken_flow_ratio == round(4 / features.flows_checked, 4)
    assert [b.key for b in flows.examples] == ["blk_70", "blk_71", "blk_72", "blk_73"]
    items = {e.id: e for e in evidence.new_items()}
    summary = items[flows.evidence_id or ""]
    assert summary.kind == EvidenceKind.FEATURE
    assert summary.title.startswith(f"4 of {features.flows_checked} HDFS blocks never finished")
    example = items[flows.examples[0].evidence_id or ""]
    assert example.kind == EvidenceKind.LOG
    assert "blk_70" in example.title
    assert "Receiving block blk_70" in (example.detail or "")
    assert flows.evidence_id in out.evidence_ids


def test_a_quiet_window_adds_no_flow_evidence() -> None:
    evidence = EvidenceStore()
    out = parse_lines(
        _hdfs_lines(150, broken=set()), system="hdfs", guard=GuardrailConfig(), evidence=evidence
    )
    assert out.batch.features.broken_flows == 0
    assert out.batch.flows.evidence_id is None
    assert all(e.source != "parser.flows" for e in evidence.new_items())
