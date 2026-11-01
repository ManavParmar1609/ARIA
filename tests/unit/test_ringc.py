"""Ring C: the shared measures, the suite runner and the evaluation report's new sections."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from aria.evals import domains, report_domains, ringc
from aria.evals import run as ev

LOGHUB = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"


def test_a_miss_rate_carries_the_exact_one_sided_bound() -> None:
    # No misses in ten cases still leaves up to about a quarter (the exact rule of three).
    assert ringc.upper_bound(0, 10) == pytest.approx(1 - 0.05 ** (1 / 10), abs=1e-4)
    assert ringc.upper_bound(3, 3) == 1.0
    assert ringc.upper_bound(0, 0) == 1.0
    rate = ringc.miss_rate(1, 4)
    assert rate["share"] == 0.25
    assert rate["upper95"] > rate["ci95"][1] - 0.1


def test_ranking_is_chance_when_every_case_has_the_same_truth() -> None:
    assert ringc.ranking([True, True], [0.1, 0.9])["auroc"] == 0.5
    perfect = ringc.ranking([False, True, False, True], [0.1, 0.9, 0.2, 0.8])
    assert perfect["auroc"] == 1.0
    assert perfect["positives"] == 2


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("ts-preserve-service", "preserve"),
        ("PreserveService", "preserve"),
        ("preserve", "preserve"),
        ("front-end", "frontend"),
        ("cartservice", "cart"),
        ("frontend-675fd7b5c5-jlpzp", "frontend"),
        ("", ""),
        (None, ""),
    ],
)
def test_service_names_match_across_naming_conventions(name: str | None, key: str) -> None:
    assert ringc.service_key(name) == key


def test_a_suspect_is_ranked_where_it_first_names_a_wanted_service() -> None:
    assert ringc.rank_of(["frontend", "ts-order-service", "carts"], ["OrderService"]) == 2
    assert ringc.rank_of(["frontend"], ["carts"]) is None
    named = ringc.localisation([1, 3, None, 5])
    assert named["top1"]["hits"] == 1
    assert named["top3"]["hits"] == 2
    assert named["named_anywhere"]["hits"] == 3


def test_candidates_put_the_leading_hypothesis_first_then_the_signal() -> None:
    values: dict[str, Any] = {
        "investigation": {
            "leading_hypothesis": "H2",
            "hypotheses": [
                {"id": "H1", "component": "cart", "confidence": 0.9},
                {"id": "H2", "component": "checkout", "confidence": 0.4},
                {"id": "H3", "component": None, "confidence": 0.8},
                {"id": "H4", "component": "cart", "confidence": 0.1},
            ],
        }
    }
    assert ringc.candidates(values) == ["checkout", "cart"]


def test_every_new_domain_is_a_suite_the_cli_accepts() -> None:
    for name in domains.SUITES:
        assert name in ev.SUITES
        assert name in domains.SOURCES
    assert ev.SUITES[-1] == "all"


async def test_a_suite_without_its_data_says_how_to_download_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aria.config import reset_caches

    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path))
    reset_caches()
    results: dict[str, Any] = {}
    await domains.add_to(results, "all", loghub_dir=LOGHUB)
    assert set(results["domains"]) == set(domains.SUITES)
    for name, summary in results["domains"].items():
        assert "aria data download --source" in summary["missing"], name
        assert results["domain_cases"][name] == []
    text = "\n".join(report_domains.render(results))
    assert "## New domains: data ARIA was never tuned on" in text
    assert text.count("No results: download it with: aria data download") == len(domains.SUITES)


async def test_running_one_new_domain_suite_skips_the_semi_synthetic_suites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aria.config import reset_caches

    monkeypatch.setenv("ARIA_DATA_DIR", str(tmp_path))
    reset_caches()
    results = await ev.run("ait-ads", loghub_dir=LOGHUB)
    assert set(results["domains"]) == {"ait-ads"}
    assert "severity" not in results
    assert "pipeline" not in results


def test_the_report_has_no_new_domain_sections_when_none_ran() -> None:
    assert report_domains.render({}) == []
    assert report_domains.render({"real": {"hadoop": {"missing": "x"}}}) == []
