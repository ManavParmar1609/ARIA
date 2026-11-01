"""A label-free drift check on each system's decided severity levels (severity/drift.py)."""

from __future__ import annotations

import numpy as np
import pytest

from aria.severity.drift import LEVELS, MIN_RUNS, level_drift, psi, psi_critical


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
