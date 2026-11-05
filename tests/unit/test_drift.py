"""A label-free drift check on each system's decided severity levels (severity/drift.py)."""

from __future__ import annotations

import numpy as np
import pytest

from aria.severity.drift import (
    LEVELS,
    MIN_RUNS,
    level_drift,
    psi,
    psi_critical,
    severe_miss_alarm,
    severe_miss_evidence,
)


def test_decided_levels_reads_each_systems_newest_runs_oldest_first() -> None:
    """The query behind the drift check hands back at most ``per_system`` runs a system, the
    newest ones, in the order they were decided, and never a visitor's own run."""
    from aria.db import repository as repo
    from aria.db.engine import get_engine, init_db

    engine = get_engine()
    init_db(engine)
    for n in range(5):
        repo.create_run(engine, f"run-a-{n}", request={}, system="a", severity=f"SEV{n % 4 + 1}")
    repo.create_run(engine, "run-b-0", request={}, system="b", severity="SEV2")
    repo.create_run(engine, "run-b-1", request={}, system="b", severity="SEV1", visitor="v-1")
    repo.create_run(engine, "run-c-0", request={}, system="c")  # not decided yet
    levels = repo.decided_levels(engine, per_system=3)
    assert levels == {"a": ["SEV3", "SEV4", "SEV1"], "b": ["SEV2"]}


def test_psi_is_zero_for_the_same_mix_and_grows_with_the_shift() -> None:
    same = ["SEV4"] * 50 + ["SEV3"] * 30 + ["SEV2"] * 15 + ["SEV1"] * 5
    assert psi(same, same) == pytest.approx(0.0, abs=1e-12)
    mild = ["SEV4"] * 40 + ["SEV3"] * 35 + ["SEV2"] * 20 + ["SEV1"] * 5
    strong = ["SEV1"] * 60 + ["SEV2"] * 40
    assert 0 < psi(same, mild) < psi(same, strong)


def test_the_cut_off_is_what_chance_alone_exceeds_one_time_in_twenty() -> None:
    rng = np.random.default_rng(5)
    mix = [0.1, 0.2, 0.3, 0.4]
    exceeded = 0
    trials = 600
    for _ in range(trials):
        a = list(rng.choice(LEVELS, size=120, p=mix))
        b = list(rng.choice(LEVELS, size=120, p=mix))
        exceeded += psi(a, b) > psi_critical(len(a), len(b))
    assert 0.02 <= exceeded / trials <= 0.09
    # More runs, a smaller shift is enough to stand out.
    assert psi_critical(1_000, 1_000) < psi_critical(50, 50)


def test_a_system_with_too_few_runs_is_not_judged() -> None:
    assert level_drift(["SEV4"] * (MIN_RUNS - 1)) is None


def test_a_clear_change_in_the_mix_is_flagged_and_a_steady_one_is_not() -> None:
    steady = ["SEV4", "SEV3", "SEV4", "SEV2"] * 30
    result = level_drift(steady)
    assert result is not None
    assert not result["shifted"]
    shifted = level_drift(["SEV4"] * 60 + ["SEV1", "SEV2"] * 30)
    assert shifted is not None
    assert shifted["shifted"]
    assert shifted["recent"]["SEV1"] == 30
    assert shifted["reference"]["SEV4"] == 60


# --- the severe-miss alarm ------------------------------------------------------------------------


def test_the_alarm_rarely_sounds_while_the_promise_holds() -> None:
    """Ville's inequality: while the true miss rate is at most the promise, the alarm sounds at
    any point of an endless sequence with probability at most alpha. Sequences of 300 checks at
    exactly the promised rate, read after every check, alarm about that often or less."""
    rng = np.random.default_rng(21)
    trials = 300
    alarms = sum(
        severe_miss_alarm(list(rng.random(300) < 0.05), epsilon=0.05)["raised"]
        for _ in range(trials)
    )
    assert alarms / trials <= 0.08
    assert not severe_miss_alarm([False] * 400, epsilon=0.05)["raised"]
    quiet = severe_miss_alarm([], epsilon=0.05)
    assert (quiet["checks"], quiet["raised"], quiet["evidence"]) == (0, False, 1.0)


def test_the_alarm_sounds_once_misses_run_above_the_promise_and_then_stays_up() -> None:
    rng = np.random.default_rng(22)
    misses = list(rng.random(200) < 0.3)
    result = severe_miss_alarm(misses, epsilon=0.05)
    assert result["raised"]
    assert result["raised_at"] is not None
    assert result["raised_at"] <= 60
    assert result["p_value"] <= 0.05
    later = severe_miss_alarm([*misses, *[False] * 1_000], epsilon=0.05)
    assert later["raised"]
    assert later["raised_at"] == result["raised_at"]
    assert later["evidence"] < result["evidence"]  # the evidence fades; the alarm does not


def test_the_evidence_is_a_likelihood_ratio_that_starts_at_one() -> None:
    assert severe_miss_evidence(0, 0, 0.05) == 1.0
    assert severe_miss_evidence(0, 20, 0.05) == pytest.approx(1 / 21)  # no misses: for the promise
    assert severe_miss_evidence(2, 3, 0.05) == pytest.approx(36.9, rel=0.01)
    assert not severe_miss_alarm([True], epsilon=0.05)["raised"]  # one miss is not enough
    assert severe_miss_alarm([True, False, True], epsilon=0.05)["raised"]
    with pytest.raises(ValueError, match="between 0 and 1"):
        severe_miss_alarm([True], epsilon=0.0)
