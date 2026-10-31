"""Statistics that never claim more than a count holds (evals/stats.py)."""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from aria.evals import stats


def test_the_upper_bound_matches_the_rule_of_three_scale() -> None:
    # No misses in 59 severe cases supports "at most 5%"; in 8, only "at most about 31%".
    assert stats.upper_bound(0, 59) == pytest.approx(0.05, abs=0.001)
    assert stats.upper_bound(0, 8) == pytest.approx(0.312, abs=0.002)
    assert stats.upper_bound(3, 3) == 1.0
    assert stats.upper_bound(0, 0) == 1.0


@given(st.integers(0, 200), st.integers(1, 200))
def test_the_bound_is_never_below_the_rate_and_grows_with_misses(hits: int, n: int) -> None:
    hits = min(hits, n)
    bound = stats.upper_bound(hits, n)
    assert hits / n <= bound <= 1.0
    if hits < n:
        assert stats.upper_bound(hits + 1, n) >= bound


@given(st.integers(0, 300), st.integers(1, 300))
def test_wilson_contains_the_rate_and_stays_in_range(hits: int, n: int) -> None:
    hits = min(hits, n)
    low, high = stats.wilson(hits, n)
    assert 0.0 <= low <= hits / n + 1e-12
    assert hits / n - 1e-12 <= high <= 1.0
    if n > 0:
        assert high > low  # never collapses to a point, even at 0/n or n/n


def test_mcnemar_needs_six_one_sided_pairs_to_reach_five_percent() -> None:
    assert stats.mcnemar_exact(5, 0) == pytest.approx(0.0625)
    assert stats.mcnemar_exact(6, 0) == pytest.approx(0.03125)
    assert stats.mcnemar_exact(0, 0) == 1.0
    assert stats.mcnemar_exact(4, 4) == 1.0


def test_holm_never_lowers_a_p_value_and_keeps_the_order() -> None:
    raw = {"a": 0.01, "b": 0.04, "c": 0.03}
    adjusted = stats.holm(raw)
    assert all(adjusted[k] >= raw[k] for k in raw)
    assert adjusted["a"] == pytest.approx(0.03)
    assert adjusted["a"] <= adjusted["c"] <= adjusted["b"]


def test_macro_mae_does_not_reward_always_saying_the_common_class() -> None:
    truth = ["SEV4"] * 18 + ["SEV1", "SEV2"]
    always_quiet = ["SEV4"] * 20
    plain_mae = sum(
        abs(stats.RANK[t] - stats.RANK[p]) for t, p in zip(truth, always_quiet, strict=True)
    ) / len(truth)
    assert stats.macro_mae(truth, always_quiet) > plain_mae
    assert stats.macro_mae(truth, truth) == 0.0


def test_severe_misses_count_only_serious_windows_rated_minor() -> None:
    truth = ["SEV1", "SEV2", "SEV2", "SEV3", "SEV4"]
    pred = ["SEV3", "SEV1", "SEV4", "SEV1", "SEV4"]
    assert stats.severe_misses(truth, pred) == (2, 3)
    assert stats.over_triage(truth, pred) == (2, 5)


def test_smooth_ece_is_zero_when_confidence_matches_accuracy() -> None:
    assert stats.smooth_ece([1.0] * 10, [True] * 10) == pytest.approx(0.0, abs=1e-9)
    overconfident = stats.smooth_ece([0.99] * 10, [True] * 5 + [False] * 5)
    assert overconfident == pytest.approx(0.49, abs=0.01)


def test_resampling_whole_groups_widens_the_interval_honestly() -> None:
    truth = ["SEV1"] * 10 + ["SEV4"] * 10
    pred = ["SEV1"] * 10 + ["SEV1"] * 10
    one_group = stats.cluster_bootstrap(stats.macro_mae, truth, pred, ["a"] * 20)
    assert one_group[0] == one_group[1]
    groups = ["a"] * 10 + ["b"] * 10
    low, high = stats.cluster_bootstrap(stats.macro_mae, truth, pred, groups)
    assert low <= stats.macro_mae(truth, pred) <= high
    assert high > low


def test_a_paired_comparison_counts_the_cases_each_method_alone_got_right() -> None:
    truth = ["SEV1", "SEV2", "SEV3", "SEV4", "SEV1"]
    a = ["SEV1", "SEV2", "SEV4", "SEV4", "SEV3"]
    b = ["SEV3", "SEV2", "SEV3", "SEV4", "SEV1"]
    result = stats.compare(truth, a, b)
    assert (result["right_only_a"], result["right_only_b"]) == (1, 2)
    # A caught the first severe window B missed; B caught the last one A missed.
    assert (result["severe_caught_only_a"], result["severe_caught_only_b"]) == (1, 1)
    delta = stats.paired_bootstrap(
        lambda t, p: sum(x == y for x, y in zip(t, p, strict=True)) / len(t),
        truth,
        a,
        b,
        ["g1", "g1", "g2", "g2", "g3"],
    )
    assert delta["low"] <= delta["delta"] <= delta["high"]
    assert math.isclose(delta["delta"], -0.2)
