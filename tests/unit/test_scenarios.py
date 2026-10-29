from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from aria.contracts import Severity
from aria.data.loghub import parse_raw_line
from aria.data.scenarios import LinePools, ScenarioBuilder

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"


@pytest.fixture(scope="module")
def builder() -> ScenarioBuilder:
    return ScenarioBuilder(LinePools.from_loghub(FIXTURES))


def test_every_catalog_mode_is_buildable_from_fixtures(builder: ScenarioBuilder) -> None:
    assert set(builder.pools.available_modes()) == set(builder.pools.modes)


def test_same_seed_gives_identical_scenarios(builder: ScenarioBuilder) -> None:
    a = builder.build("openssh.bruteforce", seed=3, nodes=4)
    b = builder.build("openssh.bruteforce", seed=3, nodes=4)
    c = builder.build("openssh.bruteforce", seed=4, nodes=4)
    assert a.lines == b.lines
    assert a.lines != c.lines


def test_bgl_scenarios_are_labelled_by_alert_tags(builder: ScenarioBuilder) -> None:
    wide = builder.build("bgl.kernel_panic", seed=1, nodes=8, incident_per_min=20)
    assert wide.label_source == "bgl_alert_tags"
    assert wide.severity == Severity.SEV1
    narrow = builder.build("bgl.ciod_link_failure", seed=1, nodes=1, incident_per_min=0.3)
    assert narrow.severity.rank >= Severity.SEV3.rank


def test_policy_escalates_with_scope(builder: ScenarioBuilder) -> None:
    small = builder.build("zookeeper.quorum_connection_loss", seed=2, nodes=1)
    large = builder.build("zookeeper.quorum_connection_loss", seed=2, nodes=5)
    assert small.severity == Severity.SEV2
    assert large.severity == Severity.SEV1


def test_benign_noise_stays_sev4_even_at_high_volume(builder: ScenarioBuilder) -> None:
    noisy = builder.build("mac.cocoa_scripting_noise", seed=5, nodes=20, incident_per_min=200)
    assert noisy.severity == Severity.SEV4


def test_quiet_windows_have_no_incident_lines(builder: ScenarioBuilder) -> None:
    quiet = builder.build_quiet("hadoop", seed=1)
    assert quiet.severity == Severity.SEV4
    assert quiet.incident_lines == 0
    assert quiet.lines


def test_suite_lines_parse_back_and_cover_all_severities(builder: ScenarioBuilder) -> None:
    suite = builder.suite(seed=11, per_mode=3, quiet_per_system=1)
    assert Counter(s.severity for s in suite).keys() == set(Severity)
    for scenario in suite[:20]:
        for line, rec in zip(scenario.lines, scenario.records, strict=True):
            assert parse_raw_line(scenario.system, line).message == rec.message
    assert all(s.synthetic for s in suite)
