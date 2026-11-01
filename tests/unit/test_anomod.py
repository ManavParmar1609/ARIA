"""AnoMod: runs read from inside the zip, their labels from the folder names, and the suite."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from aria.data import anomod as data
from aria.evals import anomod as suite
from aria.evals import report_domains

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "anomod"


def _dataset(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(root / data.ARCHIVE, "w") as bundle:
        for path in sorted(FIXTURES.rglob("*.log")):
            bundle.write(path, path.relative_to(FIXTURES).as_posix())
    return root


def test_runs_take_their_level_and_target_from_the_folder_name(tmp_path: Path) -> None:
    cases = {c.name: c for c in data.find_cases(_dataset(tmp_path / "anomod"))}
    assert set(cases) == {"Svc_Kill_Media", "Normal_Baseline", "Lv_C_security_check"}
    assert cases["Svc_Kill_Media"].level == "service"
    assert cases["Svc_Kill_Media"].target == "MediaService"
    assert cases["Lv_C_security_check"].level == "code"
    assert cases["Lv_C_security_check"].target == "ts-security-service"
    assert not cases["Normal_Baseline"].anomalous
    assert cases["Normal_Baseline"].target is None
    assert data.find_cases(tmp_path / "none") == []


def test_lines_carry_time_level_and_service_and_stack_traces_stay_attached(
    tmp_path: Path,
) -> None:
    root = _dataset(tmp_path / "anomod")
    cases = {c.name: c for c in data.find_cases(root)}
    social = data.case_lines(cases["Svc_Kill_Media"], root)
    assert social == sorted(social)
    assert any(
        line.startswith("2025-11-04T00:03:50.405057Z ERROR UserService: (UserHandler.h:190")
        for line in social
    )
    assert any(" INFO MediaService: " in line for line in social)
    train = data.case_lines(cases["Lv_C_security_check"], root)
    # Train Ticket logs in UTC+8: 02:51 local is 18:51 the day before in UTC.
    assert train[0].startswith("2025-11-03T18:51:14.340000Z ERROR ts-security-service: ")
    trace = train.index(next(line for line in train if line.startswith("at edu.fudan")))
    assert train[trace - 1].startswith("edu.fudan.common.exception.TokenException")
    assert data.case_lines(cases["Lv_C_security_check"], root, limit=2) == train[-2:]
    # The run's name, the label, is never part of a line.
    assert not any("Svc_Kill" in line or "security_check" in line for line in social + train)


def _row(
    case: str, level: str, severity: str, target: str | None, rank: int | None
) -> dict[str, Any]:
    return {
        "index": 0,
        "system": "SN",
        "case": case,
        "level": level,
        "anomalous": level != "normal",
        "target": target,
        "lines": 10,
        "services": 4,
        "error_lines": 1,
        "rank": rank,
        "rank_most_errors": None,
        "severity": severity,
        "flagged": severity != "SEV4",
        "paged": severity in ("SEV1", "SEV2"),
        "needs_review": True,
        "severe_probability": 0.5,
        "leading_mode": "component_errors",
        "candidates": [],
    }


def test_summary_counts_runs_by_level_and_scores_naming_only_where_a_service_is_named() -> None:
    rows = [
        _row("Svc_Kill_Media", "service", "SEV2", "MediaService", 1),
        _row("Perf_CPU_Contention", "performance", "SEV4", None, None),
        _row("Normal_Baseline", "normal", "SEV3", None, None),
    ]
    summary = suite.summarize(rows)
    assert summary["anomalous"] == 2
    assert summary["normal"] == 1
    assert summary["aria"]["anomalous_flagged"]["hits"] == 1
    assert summary["aria"]["normal_flagged"] == 1
    assert summary["aria"]["naming"]["top1"] == {
        "hits": 1,
        "of": 1,
        "share": 1.0,
        "ci95": (0.025, 1.0),
    }
    assert summary["baselines"]["naming_random_expected"] == {"top1": 0.25, "top3": 0.75}
    assert summary["by_level"]["performance"]["severity"]["SEV4"] == 1
    text = "\n".join(report_domains._anomod(summary))
    assert "### Anomalies at four levels in two microservice systems" in text
    assert "| Service | 1 |" in text
    assert suite.summarize([]) == suite.MISSING
