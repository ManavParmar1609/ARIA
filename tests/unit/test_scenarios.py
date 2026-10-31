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


# --- console samples ------------------------------------------------------------------------------


def test_every_sample_has_a_plain_card_under_a_known_source(builder: ScenarioBuilder) -> None:
    cards = {key: mode.card for key, mode in builder.pools.modes.items()}
    assert all(cards.values()), [key for key, card in cards.items() if card is None]
    by_source = Counter(card.source for card in cards.values() if card)
    assert by_source == {"security": 2, "web": 3, "bigdata": 4, "hpc": 9, "noise": 3}
    headlines = [key for key, card in cards.items() if card and card.headline]
    assert 3 <= len(headlines) <= 4
    for card in cards.values():
        assert card
        assert card.title[0].isupper()
        assert not card.title.endswith(".")
        assert card.summary.endswith(".")


def test_a_sample_shows_its_failure_on_every_server_it_names(builder: ScenarioBuilder) -> None:
    for servers in (2, 6, 24):
        scenario = builder.sample("openssh.bruteforce", servers=servers)
        assert len(scenario.nodes) == servers
    # The evaluation's windows leave spread to chance, as before.
    sparse = builder.build("openssh.bruteforce", seed=3, nodes=24, incident_per_min=2)
    assert len(sparse.nodes) < 24


def test_a_size_is_offered_only_where_it_changes_the_severity(builder: ScenarioBuilder) -> None:
    ssh = builder.sample_sizes("openssh.bruteforce")
    assert ssh.servers is not None
    assert ssh.rate is None  # brute force escalates by spread, never by rate
    labels = [builder.sample("openssh.bruteforce", servers=n).severity for n in ssh.servers.values]
    assert len(set(labels)) == len(labels)  # each choice leads somewhere new
    assert [s.rank for s in labels] == sorted((s.rank for s in labels), reverse=True)
    # HDFS logs name no servers, so only the rate can matter; ZooKeeper's "peers" are threads.
    assert builder.sample_sizes("hdfs.block_serve_exceptions").servers is None
    assert builder.sample_sizes("zookeeper.quorum_connection_loss").servers is None
    for noise in ("mac.cocoa_scripting_noise", "android.permission_noise"):
        sizes = builder.sample_sizes(noise)
        assert (sizes.servers, sizes.rate) == (None, None)
        assert builder.sample(noise).severity == Severity.SEV4


def test_a_sample_reads_the_same_every_time(builder: ScenarioBuilder) -> None:
    first = builder.sample("bgl.kernel_panic", servers=4)
    again = builder.sample("bgl.kernel_panic", servers=4)
    assert first.lines == again.lines
    assert builder.sample("bgl.kernel_panic").lines != first.lines


def test_the_tricky_sample_carries_a_line_the_guard_catches(builder: ScenarioBuilder) -> None:
    from aria.security.injection import scan

    scenario = builder.sample("openssh.bruteforce")
    findings = scan(scenario.lines)
    assert len(findings) == 1
    assert "ignore previous instructions" in scenario.lines[findings[0].line_idx]
    assert parse_raw_line("openssh", scenario.lines[findings[0].line_idx]) is not None
    assert not scan(builder.sample("linux.auth_failures").lines)


def test_a_preview_shows_real_lines_from_the_sample(builder: ScenarioBuilder) -> None:
    preview = builder.preview("hdfs.block_serve_exceptions")
    assert len(preview) == 3
    assert len(set(preview)) == 3
    assert all("Got exception while serving" in line for line in preview)


def test_a_title_counts_one_client_in_the_singular() -> None:
    from aria.data.scenarios import _counted

    template = "Clients cannot connect through the proxy ({nodes} clients)"
    assert _counted(template, 1) == "Clients cannot connect through the proxy (1 client)"
    assert _counted(template, 3) == "Clients cannot connect through the proxy (3 clients)"
