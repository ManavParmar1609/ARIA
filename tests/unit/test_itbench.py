"""ITBench-Lite: the service at fault from the ground truth, what ARIA is paged with, the log
window the download keeps, and the suite's scores."""

from __future__ import annotations

import gzip
import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from aria.data import itbench as data
from aria.data.manifest import DataSource, Stream
from aria.evals import itbench as suite
from aria.evals import report_domains

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "itbench"
COMMIT = "d0916b08ba421ce5e672e9ad68aa947d938dfef0"


def _dataset(root: Path) -> Path:
    shutil.copytree(FIXTURES, root)
    window = next(root.rglob("logs_window.tsv"))
    (window.parent / data.WINDOW_FILE).write_bytes(gzip.compress(window.read_bytes()))
    window.unlink()
    return root


def test_the_service_at_fault_follows_a_non_workload_root_cause_to_the_first_workload(
    tmp_path: Path,
) -> None:
    [scenario] = data.find_scenarios(_dataset(tmp_path / "itbench"))
    assert scenario.id == "Scenario-2"
    assert scenario.root_kinds == ("ConfigMap",)  # a feature flag set in a ConfigMap
    assert scenario.services == ("cart",)  # the workload the flag breaks first
    assert scenario.raised_at == datetime(2025, 12, 15, 17, 52, 23, 904312, tzinfo=UTC)
    assert "frontend-proxy" in scenario.alert_services


def test_workloads_are_named_without_their_pod_and_replica_set_suffixes() -> None:
    assert data.workload("frontend-675fd7b5c5-jlpzp") == "frontend"
    assert data.workload("valkey-cart-58df56c79c") == "valkey-cart"
    assert data.workload("kafka") == "kafka"
    truth = {
        "groups": [
            {"id": "ad-pod-1", "kind": "Pod", "filter": ["ad-.*"], "root_cause": True},
            {"id": "frontend-service-1", "kind": "Service", "filter": ["frontend\\b"]},
        ]
    }
    assert data.services_at_fault(truth) == (("ad",), ("Pod",))


def test_a_ground_truth_wrapped_as_a_kubernetes_object_reads_the_same(tmp_path: Path) -> None:
    path = tmp_path / "ground_truth.yaml"
    path.write_text(
        "apiVersion: itbench.io/v1\nkind: GroundTruth\nspec:\n  groups:\n"
        "    - id: catalog-deployment-1\n      kind: Deployment\n"
        "      filter: ['product-catalog-.*']\n      root_cause: true\n"
    )
    assert data.services_at_fault(data.ground_truth(path)) == (
        ("product-catalog",),
        ("Deployment",),
    )
    path.write_text("- not a mapping\n")
    assert data.ground_truth(path) == {}


def test_alerts_arrive_as_alertmanager_sends_them(tmp_path: Path) -> None:
    [scenario] = data.find_scenarios(_dataset(tmp_path / "itbench"))
    alerts = data.alerts(scenario)
    assert [a.labels["service_name"] for a in alerts] == ["frontend-proxy", "fraud-detection"]
    assert all(a.source == "alertmanager" and a.status == "firing" for a in alerts)
    assert suite.alert_severity(alerts) == "SEV3"  # warnings flag; nothing is critical
    assert suite.alerted_services(alerts) == ["frontend-proxy", "fraud-detection"]


def test_events_and_logs_become_lines_ending_when_the_incident_was_raised(
    tmp_path: Path,
) -> None:
    [scenario] = data.find_scenarios(_dataset(tmp_path / "itbench"))
    early = datetime(2025, 12, 15, 17, 0, tzinfo=UTC)
    events = data.event_lines(scenario, early, scenario.raised_at or early)
    assert len(events) == 2
    assert any(" WARN " in line for _, line in events)  # a Warning event reads as a warning
    logs = data.log_lines(scenario)
    assert logs
    assert all(" INFO cart: " in line or " INFO frontend: " in line for _, line in logs)
    lines = data.scenario_lines(scenario, suite.WINDOW_MIN)
    assert lines == [line for _, line in logs]  # the two events are older than ten minutes
    assert not any("flagd-config" in line for line in lines)  # the ground truth stays out


def _log_tsv(rows: list[tuple[str, str]]) -> bytes:
    header = "\t".join(
        [
            "Timestamp",
            "TimestampTime",
            "TraceId",
            "SpanId",
            "TraceFlags",
            "SeverityText",
            "SeverityNumber",
            "ServiceName",
            "Body",
            "ResourceSchemaUrl",
            "ResourceAttributes",
        ]
    )
    body = [
        "\t".join([ts, ts[:19], "", "", "0", "Error", "17", service, '"multi\nline body"', "", ""])
        for ts, service in rows
    ]
    return (header + "\n" + "\n".join(body) + "\n").encode()


@respx.mock
def test_the_download_keeps_the_newest_lines_of_the_window_and_checks_the_whole_log(
    tmp_path: Path,
) -> None:
    root = _dataset(tmp_path / "itbench")
    next(root.rglob(data.WINDOW_FILE)).unlink()
    folder = next(root.rglob("Scenario-2")).relative_to(root).as_posix()
    log = _log_tsv(
        [
            ("2025-12-15 17:30:00.000000000", "cart"),  # before the window
            ("2025-12-15 17:45:00.000000000", "cart"),
            ("2025-12-15 17:50:00.000000000", "frontend"),
            ("2025-12-15 17:52:00.000000000", "checkout"),
            ("2025-12-15 18:10:00.000000000", "cart"),  # after the incident was raised
        ]
    )
    listing = [
        {
            "type": "file",
            "path": f"{folder}/otel_logs_raw.tsv",
            "lfs": {"oid": hashlib.sha256(log).hexdigest()},
        }
    ]
    tree = respx.get(url__regex=r"https://huggingface\.co/api/datasets/.*/tree/.*").mock(
        return_value=httpx.Response(200, json=listing)
    )
    respx.get(url__regex=r".*/resolve/.*/otel_logs_raw\.tsv").mock(
        return_value=httpx.Response(200, content=log)
    )
    source = DataSource(
        name="itbench-lite",
        kind="huggingface",
        url="https://huggingface.co/datasets/ibm-research/ITBench-Lite",
        commit=COMMIT,
        paths=["x"],
        stream=Stream(reader="itbench-logs", minutes=10, limit=2),
        license="Apache-2.0",
        citation="c",
        description="d",
    )
    with httpx.Client() as client:
        [written] = data.write_log_windows(source, root, client, None)
    rows = list(data._rows(written))
    assert [r[1] for r in rows] == ["frontend", "checkout"]  # the newest two of three in span
    assert rows[0][4] == "multi\nline body"
    written.unlink()
    tree.mock(return_value=httpx.Response(200, json=[{**listing[0], "lfs": {"oid": "0" * 64}}]))
    with httpx.Client() as client, pytest.raises(Exception, match="sha256 mismatch"):
        data.write_log_windows(source, root, client, None)


def test_the_window_keeps_rows_in_time_order() -> None:
    rows = [
        [
            "2025-12-15 17:51:00",
            "",
            "",
            "",
            "",
            "INFO",
            "",
            "b",
            "two",
            "",
            "{'k8s.pod.name': 'b-1'}",
        ],
        ["2025-12-15 17:50:00", "", "", "", "", "INFO", "", "a", "one", "", ""],
        ["short row"],
    ]
    since = datetime(2025, 12, 15, 17, 45, tzinfo=UTC)
    until = datetime(2025, 12, 15, 17, 55, tzinfo=UTC)
    kept = data.keep_window(iter(rows), since, until)
    assert [k[4] for k in kept] == ["one", "two"]
    assert kept[1][2] == "b-1"
    assert data.keep_window(iter(rows), since, until, limit=1)[0][4] == "two"


def _row(index: int, severity: str, rank: int | None, kinds: list[str]) -> dict[str, Any]:
    return {
        "index": index,
        "scenario": f"Scenario-{index}",
        "categories": ["Resource Unavailable"],
        "root_kinds": kinds,
        "targets": ["cart"] if rank is not None or kinds == ["Pod"] else [],
        "alerts": 2,
        "lines": 100,
        "services": 5,
        "error_lines": 3,
        "alert_severity": "SEV3",
        "rank": rank,
        "rank_alerted": None,
        "rank_most_errors": 2,
        "severity": severity,
        "flagged": severity != "SEV4",
        "paged": severity in ("SEV1", "SEV2"),
        "needs_review": True,
        "severe_probability": 0.4,
        "leading_mode": "component_errors",
        "candidates": ["cart"],
    }


def test_summary_counts_incidents_flagged_and_services_named() -> None:
    rows = [
        _row(1, "SEV2", 1, ["Pod"]),
        _row(2, "SEV4", None, ["Pod"]),
        _row(3, "SEV3", 3, ["ConfigMap"]),
    ]
    summary = suite.summarize(rows)
    assert summary["aria"]["flagged"]["hits"] == 2
    assert summary["aria"]["missed"]["hits"] == 1
    assert summary["aria"]["naming"]["top3"]["hits"] == 2
    assert summary["by_root_kind"]["not a workload"]["scenarios"] == 1
    assert summary["baselines"]["alert_severity"]["flagged"]["hits"] == 3
    summary["found"] = 4
    text = "\n".join(report_domains._itbench(summary))
    assert "### Kubernetes incidents" in text
    assert "1 scenario has no incident time" in text
    assert suite.summarize([]) == suite.MISSING
