"""How each reviewer decides: the figures Settings shows, from the reviews ARIA keeps."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from aria.api.reviewers import reviewer_stats, wait_s

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)


def decision(
    reviewer: str,
    kind: str,
    *,
    waited_s: float | None = 60.0,
    aria: str = "SEV2",
    final: str | None = None,
) -> dict[str, Any]:
    return {
        "run_id": f"run-{reviewer}-{kind}",
        "reviewer": reviewer,
        "decision": kind,
        "aria_level": aria,
        "final_level": final or aria,
        "paused_at": T0 if waited_s is not None else None,
        "decided_at": T0 + timedelta(seconds=waited_s or 0),
    }


def test_each_reviewer_gets_their_own_approvals_level_changes_and_median_wait() -> None:
    ana, raj = reviewer_stats(
        [
            decision("ana", "approve", waited_s=60),
            decision("raj", "reject", waited_s=None),  # the run's pause was never recorded
            decision("ana", "approve", waited_s=180),
            decision("ana", "edit", waited_s=600, final="SEV1"),
        ]
    )
    assert (ana.reviewer, ana.decisions, ana.approved_as_is, ana.edited, ana.rejected) == (
        "ana",
        3,
        2,
        1,
        0,
    )
    assert ana.level_changed == 1
    assert ana.median_wait_s == 180.0
    assert (raj.decisions, raj.rejected, raj.level_changed) == (1, 1, 0)
    assert raj.median_wait_s is None  # nothing to time, so nothing is guessed


def test_an_edit_that_keeps_aria_s_level_is_an_edit_but_no_level_change() -> None:
    [ana] = reviewer_stats([decision("ana", "edit", final="SEV2")])
    assert (ana.edited, ana.level_changed, ana.approved_as_is) == (1, 0, 0)


def test_a_decision_never_reads_as_earlier_than_the_pause_it_answers() -> None:
    assert wait_s(T0, T0 - timedelta(seconds=2)) == 0.0  # two processes' clocks disagree a little
    assert wait_s(None, T0) is None
    assert wait_s(T0, None) is None


@given(
    st.lists(
        st.tuples(
            st.sampled_from(["ana", "raj", "li"]),
            st.sampled_from(["approve", "edit", "reject"]),
            st.floats(min_value=0, max_value=86_400),
        ),
        max_size=30,
    )
)
def test_the_figures_add_up_to_the_decisions_read(rows: list[tuple[str, str, float]]) -> None:
    stats = reviewer_stats(decision(r, kind, waited_s=w) for r, kind, w in rows)
    assert sum(s.decisions for s in stats) == len(rows)
    for s in stats:
        assert s.approved_as_is + s.edited + s.rejected == s.decisions
        assert 0 <= s.level_changed <= s.decisions
        assert s.median_wait_s is None or min(s.waits_s) - 0.1 <= s.median_wait_s
    assert [s.decisions for s in stats] == sorted((s.decisions for s in stats), reverse=True)
