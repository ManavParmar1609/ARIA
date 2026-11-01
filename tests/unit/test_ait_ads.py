"""The AIT Alert Data Set: alerts as lines, windows labelled by attack steps, and the suite."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from aria.data import ait_ads as data
from aria.evals import ait_ads as suite
from aria.evals import report_domains

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ait-ads"


def _dataset(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "labels.csv").write_bytes((FIXTURES / "labels.csv").read_bytes())
    with zipfile.ZipFile(root / data.ARCHIVE, "w") as bundle:
        for name in ("russellmitchell_wazuh.json", "russellmitchell_aminer.json"):
            bundle.write(FIXTURES / name, name)
    return root


def test_attack_steps_are_read_per_scenario_in_time_order() -> None:
    phases = data.read_phases(FIXTURES)
    steps = phases["russellmitchell"]
    assert [p.start for p in steps] == sorted(p.start for p in steps)
    assert {"dirb", "webshell", "dnsteal"} <= {p.name for p in steps}


def test_each_alert_becomes_one_line_with_its_time_host_and_text(tmp_path: Path) -> None:
    alerts = list(data.iter_alerts("russellmitchell", _dataset(tmp_path / "ait")))
    assert [a.ts for a in alerts] == sorted(a.ts for a in alerts)
    assert {a.source for a in alerts} == {"wazuh", "suricata", "aminer"}
    suricata = next(a for a in alerts if a.source == "suricata")
    assert " suricata: Not Suspicious Traffic: ET POLICY" in suricata.line
    web = next(a for a in alerts if "rule 31101 " in a.line)
    assert web.level == 5  # Wazuh's own rule level is kept beside the line
    assert web.line.startswith("2022-01-24T")
    assert " wazuh rule 31101 level 5: Web server 400 error code. " in web.line
    aminer = next(a for a in alerts if a.source == "aminer")
    assert aminer.level is None
    assert " aminer: AMiner: " in aminer.line
    # The labels never reach a line.
    assert not any("dirb" in a.line.lower() for a in alerts)


def test_records_that_are_not_alerts_are_skipped() -> None:
    assert data.wazuh_alert({"@timestamp": "not a time"}) is None
    assert data.aminer_alert({"LogData": {"Timestamps": []}}) is None


def test_windows_are_labelled_by_the_attack_steps_they_overlap(tmp_path: Path) -> None:
    root = _dataset(tmp_path / "ait")
    phases = data.read_phases(root)["russellmitchell"]
    windows = list(data.windows(data.iter_alerts("russellmitchell", root), phases, "r", 20))
    assert sum(len(w.alerts) for w in windows) == len(
        list(data.iter_alerts("russellmitchell", root))
    )
    attack = [w for w in windows if w.phases]
    assert attack
    assert all("dirb" in w.phases or "wpscan" in w.phases for w in attack)
    assert any(not w.phases for w in windows)  # the routine alerts from hours earlier
    assert all(w.end - w.start == 20 * 60 for w in windows)


def test_scenario_windows_are_judged_with_the_networks_own_history(tmp_path: Path) -> None:
    rows = suite.score_scenario("russellmitchell", _dataset(tmp_path / "ait"))
    assert rows
    assert {r["severity"] for r in rows} <= {"SEV1", "SEV2", "SEV3", "SEV4"}
    attack = [r for r in rows if r["attack"]]
    assert attack
    assert attack[0]["max_level"] >= 5
    assert all(0.0 <= r["severe_probability"] <= 1.0 for r in rows)
    assert data.scenarios(tmp_path / "missing") == []


def _row(scenario: str, phases: list[str], severity: str, level: int, p: float) -> dict[str, Any]:
    return {
        "scenario": scenario,
        "start": "2022-01-24T00:00:00+00:00",
        "alerts": 10,
        "read": 10,
        "max_level": level,
        "phases": phases,
        "attack": bool(phases),
        "harmful": any(x in suite.HARMFUL for x in phases),
        "severity": severity,
        "rules": severity,
        "model": severity,
        "keyword": "SEV4",
        "needs_review": False,
        "severe_probability": p,
        "fired": ["errors_present"] if severity in ("SEV1", "SEV2") else [],
    }


def test_summary_ranks_windows_and_counts_missed_harmful_steps() -> None:
    phases = {
        "a": [
            data.Phase("a", "dirb", 0.0, 10.0),
            data.Phase("a", "webshell", 20.0, 30.0),
            data.Phase("a", "dnsteal", 40.0, 50.0),
        ]
    }
    rows = [
        _row("a", ["dirb"], "SEV2", 10, 0.9),
        _row("a", ["webshell"], "SEV4", 12, 0.2),
        _row("a", [], "SEV4", 3, 0.1),
        _row("a", [], "SEV3", 5, 0.3),
    ]
    summary = suite.summarize(rows, phases)
    assert summary["attack_windows"] == 2
    assert summary["routine_windows"] == 2
    steps = summary["steps"]["aria"]
    # webshell's window was not paged, and dnsteal raised no alert at all: two misses of two.
    assert steps["harmful_occurrences"] == 2
    assert steps["harmful_without_alerts"] == 1
    assert steps["severe_miss"]["hits"] == 2
    assert steps["severe_miss"]["upper95"] == 1.0
    # The detectors' own level pages at 12 or above: the web shell window.
    assert summary["steps"]["ids_level"]["severe_miss"]["hits"] == 1
    assert summary["rates"]["aria"]["routine_flagged"]["hits"] == 1
    assert summary["ranking"]["aria_probability"]["auroc"] == 0.75
    assert summary["per_scenario"]["a"]["attack_windows"] == 2
    text = "\n".join(report_domains._ait(summary))
    assert "### Security alerts from attacked networks" in text
    assert "| Web shell upload | 1 | 1 | 0 | 0 |" in text
    assert suite.summarize([], phases) == suite.MISSING


async def test_the_suite_scores_every_scenario_in_the_download(tmp_path: Path) -> None:
    summary, rows = await suite.evaluate(_dataset(tmp_path / "ait"), limit=2)
    assert summary["scenarios"] == 1
    assert summary["windows"] == len(rows) <= 2
    missing, none = await suite.evaluate(tmp_path / "nothing")
    assert missing == suite.MISSING
    assert none == []
    assert json.dumps(summary)  # the summary is plain JSON
