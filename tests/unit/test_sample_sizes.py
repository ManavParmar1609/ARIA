"""Sample sizes chosen by how a run rates the sample, saved by `aria seed`, checked on load."""

from __future__ import annotations

from pathlib import Path

import pytest

from aria.config import get_app_config, get_settings
from aria.contracts import Severity
from aria.data.scenarios import (
    LinePools,
    Rating,
    SampleSizes,
    Scenario,
    ScenarioBuilder,
    SizeChoice,
)
from aria.severity import samples

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"


@pytest.fixture
def builder() -> ScenarioBuilder:
    return ScenarioBuilder(LinePools.from_loghub(FIXTURES))


def _by_servers(ratings: dict[int, Severity], rest: Severity) -> Rating:
    def rating(scenario: Scenario) -> Severity:
        return ratings.get(int(scenario.label_detail["nodes"]), rest)

    return rating


def test_a_size_is_offered_only_where_the_rating_gets_more_serious(
    builder: ScenarioBuilder,
) -> None:
    # 6 servers rated less serious than 4 would read as a mistake, so it is left out.
    builder.rate_with(
        _by_servers(
            {2: Severity.SEV3, 3: Severity.SEV3, 4: Severity.SEV2, 6: Severity.SEV3},
            Severity.SEV1,
        )
    )
    sizes = builder.sample_sizes("openssh.bruteforce")
    assert sizes.servers == SizeChoice((2, 4, 8))
    assert sizes.rate is None  # at the default 2 servers every rate rates the same


def test_a_size_that_changes_no_rating_is_not_offered(builder: ScenarioBuilder) -> None:
    builder.rate_with(lambda _: Severity.SEV2)
    assert builder.sample_sizes("openssh.bruteforce") == SampleSizes()
    # Bigger but less serious, only: still nothing to choose.
    builder.rate_with(_by_servers({2: Severity.SEV1}, Severity.SEV3))
    assert builder.sample_sizes("openssh.bruteforce").servers is None


def test_saved_sizes_are_used_only_while_their_inputs_are_unchanged(tmp_path: Path) -> None:
    sizes = {
        "openssh.bruteforce": SampleSizes(SizeChoice((2, 8, 16)), None),
        "hdfs.block_serve_exceptions": SampleSizes(None, SizeChoice((12, 60))),
        "mac.cocoa_scripting_noise": SampleSizes(),
    }
    path = tmp_path / samples.SIZES_FILE
    samples.save_sizes(path, sizes, "inputs-a")
    assert samples.load_sizes(path, "inputs-a") == sizes
    assert samples.load_sizes(path, "inputs-b") is None  # rated from other inputs
    assert samples.load_sizes(tmp_path / "missing.json", "inputs-a") is None
    path.write_text('{"fingerprint": "inputs-a", "sizes": {"x": {"servers": [0, 2]}}}')
    assert samples.load_sizes(path, "inputs-a") is None  # unreadable: the labels serve instead


def test_the_fingerprint_follows_the_lines_and_the_model_in_use(tmp_path: Path) -> None:
    settings, config = get_settings(), get_app_config()
    first = samples.fingerprint(settings, config, FIXTURES)
    assert samples.fingerprint(settings, config, FIXTURES) == first
    assert samples.fingerprint(settings, config, tmp_path) != first  # other lines
    # A recalibrated model in the models directory rates differently.
    recalibrated = settings.model_copy(update={"models_dir": tmp_path})
    assert samples.fingerprint(recalibrated, config, FIXTURES) == first
    (tmp_path / Path(config.severity.log_model_file).name).write_text("{}")
    assert samples.fingerprint(recalibrated, config, FIXTURES) != first
