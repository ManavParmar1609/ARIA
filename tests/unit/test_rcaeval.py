"""RCAEval RE3: cases read from inside their zip, split at the fault, and the suite's scores."""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from typing import Any

import pytest

from aria.data import rcaeval as data
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.evals import pipeline as pl
from aria.evals import rcaeval as suite
from aria.evals import report_domains

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rcaeval"
LOGHUB = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"


def _dataset(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(root / "RE3-SS.zip", "w") as bundle:
        for path in sorted((FIXTURES / "RE3-SS").rglob("*")):
            name = path.relative_to(FIXTURES).as_posix() + ("/" if path.is_dir() else "")
            if path.is_dir():
                bundle.writestr(name, b"")
            else:
                bundle.write(path, name)
    return root


def test_cases_are_read_from_inside_the_zip_with_their_label(tmp_path: Path) -> None:
    cases = data.find_cases(_dataset(tmp_path / "rca"))
    assert len(cases) == 1
    case = cases[0]
    assert (case.system, case.service, case.fault, case.repetition) == ("SS", "carts", "f1", "1")
    assert case.id == "SS/carts_f1/1"
    assert data.find_cases(tmp_path / "none") == []


def test_logs_split_at_the_fault_and_each_line_is_led_by_its_container(tmp_path: Path) -> None:
    split = data.windows(data.find_cases(_dataset(tmp_path / "rca"))[0])
    assert split.injected_at == 1732243203.0
    assert split.before
    assert split.after
    assert all(line < "2024-11-22T02:40:03" for line in split.before)
    assert all(line >= "2024-11-22T02:40:03" for line in split.after)
    assert split.after[-1].startswith("2024-11-22T02:40:03.479076Z carts: 2024-11-22 02:40:03")
    assert split.services_after["carts"] == 3
    # The folder name, the label, is never part of a line.
    assert not any("carts_f1" in line for line in split.before + split.after)


def test_volume_change_ranks_the_container_whose_share_moved_most() -> None:
    ranked = suite._most_changed({"a": 50, "b": 50}, {"a": 10, "b": 50, "c": 40})
    assert ranked[0] in {"a", "c"}
    assert ranked[-1] == "b"


def _row(case: str, window: str, severity: str, rank: int | None) -> dict[str, Any]:
    return {
        "index": 0,
        "case": case,
        "system": "SS",
        "service": "carts",
        "fault": "f1",
        "window": window,
        "faulty": window == "faulty",
        "lines": 10,
        "containers": 5,
        "error_lines": 3 if window == "faulty" else 0,
        "rank": rank,
        "rank_most_errors": 2,
        "rank_most_changed": 1,
        "severity": severity,
        "flagged": severity in ("SEV1", "SEV2", "SEV3"),
        "paged": severity in ("SEV1", "SEV2"),
        "needs_review": True,
        "severe_probability": {"SEV2": 0.6, "SEV3": 0.3, "SEV4": 0.1}[severity],
        "leading_mode": "component_errors",
        "candidates": ["carts"],
    }


def test_summary_pairs_each_faulty_window_with_its_healthy_one() -> None:
    rows = [
        _row("SS/carts_f1/1", "faulty", "SEV2", 1),
        _row("SS/carts_f1/1", "healthy", "SEV4", None),
        _row("SS/carts_f1/2", "faulty", "SEV3", None),
        _row("SS/carts_f1/2", "healthy", "SEV3", None),
    ]
    summary = suite.summarize(rows)
    aria = summary["aria"]
    assert aria["paired"] == {"higher": 1, "same": 1, "lower": 0}
    assert aria["faulty_flagged"]["hits"] == 2
    assert aria["healthy_flagged"]["hits"] == 1
    assert aria["naming"]["top1"]["hits"] == 1
    assert aria["naming"]["top3"]["of"] == 2
    assert summary["baselines"]["naming_most_changed"]["top1"]["hits"] == 2
    assert summary["baselines"]["naming_random_expected"] == {"top1": 0.2, "top3": 0.6}
    text = "\n".join(report_domains._rcaeval(summary))
    assert "### Code-level faults in microservice shops" in text
    assert "1 cases ARIA rated the faulty window above its own healthy window" in text
    assert suite.summarize([]) == suite.MISSING


@pytest.fixture(scope="module")
def builder() -> ScenarioBuilder:
    return ScenarioBuilder(LinePools.from_loghub(LOGHUB))


async def test_each_window_is_triaged_end_to_end_without_its_label(
    tmp_path: Path, builder: ScenarioBuilder
) -> None:
    root = _dataset(tmp_path / "rca")
    with tempfile.TemporaryDirectory() as tmp:
        env = await pl.EvalEnvironment.create(builder, db_path=Path(tmp) / "e.db")
        try:
            rows = await suite.triage(env, None, root)
        finally:
            await env.aclose()
    assert [r["window"] for r in rows] == ["healthy", "faulty"]
    assert all(r["severity"] in {"SEV1", "SEV2", "SEV3", "SEV4"} for r in rows)
    assert rows[1]["containers"] == 3
    assert rows[1]["service"] == "carts"
    assert "rank_most_changed" in rows[1]
