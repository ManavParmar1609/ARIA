"""Nezha's Online Boutique data: the streamed archive reader, fault windows and the suite."""

from __future__ import annotations

import gzip
import io
import json
import lzma
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import pytest
import respx
from test_download import _ranged, _zenodo_record, _zip_bytes

from aria.data import nezha as data
from aria.data.download import DownloadError, download
from aria.data.manifest import DataSource, Stream, load_manifest
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.evals import nezha as suite
from aria.evals import pipeline as pl
from aria.evals import report_domains

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nezha"
LOGHUB = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"
HEADER = "Timestamp,TimeUnixNano,Node,PodName,Container,TraceID,SpanID,Log\n"
FAULT_AT = 1661140434  # 2022-08-22T03:53:54Z


def _dataset(root: Path) -> Path:
    """The committed excerpt, gzipped as the download stores it."""
    shutil.copytree(FIXTURES, root)
    for path in root.rglob("*.tsv"):
        path.with_name(path.name + ".gz").write_bytes(gzip.compress(path.read_bytes()))
        path.unlink()
    return root


def test_faults_come_from_each_days_fault_list(tmp_path: Path) -> None:
    faults = data.find_faults(_dataset(tmp_path / "nezha"))
    assert [f.at for f in faults] == sorted(f.at for f in faults)
    assert {f.folder for f in faults} == {"dataset1"}
    assert {f.day for f in faults} == {"2022-08-22"}
    first = faults[0]
    assert first.service == "frontend"  # the pod's workload
    assert first.kind == "exception"
    assert first.id == "2022-08-22T04:18:35 frontend"
    assert data.find_faults(tmp_path / "none") == []


def test_where_the_lists_two_times_disagree_neither_window_holds_the_gap() -> None:
    same = data.Fault("d", "f", at=1000.0, pod="p-1-2", kind="return", noted_at=1000.0)
    assert same.spans(1) == ((940.0, 1000.0), (1000.0, 1060.0))
    late_label = data.Fault("d", "f", at=1000.0, pod="p-1-2", kind="return", noted_at=1060.0)
    assert late_label.spans(1) == ((940.0, 1000.0), (1060.0, 1120.0))
    early_label = data.Fault("d", "f", at=1000.0, pod="p-1-2", kind="return", noted_at=956.0)
    assert early_label.spans(1) == ((896.0, 956.0), (1000.0, 1060.0))
    [listed] = data.parse_faults(
        {"07": [{"inject_time": "2022-08-22 07:10:43", "inject_timestamp": "1661152183"}]},
        "2022-08-22",
        "dataset1",
    )
    assert listed.noted_at == 1661152243.0  # a minute after the timestamp


def test_a_window_reads_every_file_that_can_hold_its_lines() -> None:
    # A file holds about the minute before its name, so a window reaches one file further.
    assert data.minute_files(FAULT_AT - 60, FAULT_AT + 60) == ["03_52", "03_53", "03_54", "03_55"]


@pytest.mark.parametrize(
    ("raw", "level", "text"),
    [
        (
            json.dumps({"log": json.dumps({"message": "charged", "severity": "info"}) + "\n"}),
            "INFO",
            "charged",
        ),
        (
            json.dumps(
                {
                    "log": json.dumps(
                        {
                            "error": "rpc error: code = Unavailable",
                            "http.resp.status": 500,
                            "message": "request error",
                            "severity": "error",
                            "timestamp": "2022-08-22T04:18:40Z",
                        }
                    )
                }
            ),
            "ERROR",
            'request error error="rpc error: code = Unavailable" http.resp.status=500',
        ),
        (json.dumps({"log": "plain text line\n"}), None, "plain text line"),
        ("not json at all", None, "not json at all"),
        (json.dumps({"log": "{not json"}), None, "{not json"),
        (json.dumps(["a list"]), None, '["a list"]'),
    ],
)
def test_a_container_log_record_yields_its_level_and_message(
    raw: str, level: str | None, text: str
) -> None:
    assert data.message(raw) == (level, text)


def test_a_fault_splits_the_logs_around_it_and_never_shows_its_label(tmp_path: Path) -> None:
    root = _dataset(tmp_path / "nezha")
    fault = data.find_faults(root)[0]
    split = data.windows(fault, root, minutes=1)
    assert split.before
    assert split.after
    assert split.before == sorted(split.before)
    assert split.after == sorted(split.after)
    assert split.before[-1] < "2022-08-22T04:18:35" <= split.after[0]
    assert split.after[-1] < "2022-08-22T04:19:35"
    assert sum(split.services_before.values()) == len(split.before)
    assert sum(split.services_after.values()) == len(split.after)
    assert not any("inject" in line for line in split.before + split.after)
    assert len(set(split.before + split.after)) == len(split.before + split.after)


def _minute_csv(ns: int, pod: str, message: str) -> str:
    log = json.dumps({"log": json.dumps({"message": message, "severity": "info"}) + "\n"})
    escaped = log.replace('"', '""')
    return HEADER + f'2022-08-22T00:00:00Z,{ns},1.1.1.1,{pod},server,t,s,"{escaped}"\n'


FAULT_LIST = json.dumps(
    {
        "03": [
            {
                "inject_time": "2022-08-22 03:53:10",
                "inject_timestamp": str(FAULT_AT),
                "inject_pod": "frontend-579b9bff58-t2dbm",
                "inject_type": "cpu_contention",
            }
        ]
    }
)
NEAR = ("dataset1/log/03_53_log.csv", FAULT_AT, "frontend-579b9bff58-t2dbm", "request complete")
FAR = ("dataset1/log/07_00_log.csv", 1661151600, "cartservice-1-2", "far")


def _archive(*, list_first: bool = True, with_list: bool = True) -> bytes:
    """A day's tar.xz: its fault list, a log file near the fault, one far from it, a trace."""
    logs = {name: _minute_csv(at * 10**9, pod, text) for name, at, pod, text in (FAR, NEAR)}
    listed = {"dataset1/2022-08-22-fault_list.json": FAULT_LIST} if with_list else {}
    trace = {"dataset1/trace/03_53_trace.csv": "time,trace\n"}
    members = {**listed, **trace, **logs} if list_first else {**logs, **trace, **listed}
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, text in members.items():
            payload = text.encode()
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return lzma.compress(buffer.getvalue())


def _chunks(payload: bytes, size: int = 500) -> Any:
    return iter([payload[i : i + size] for i in range(0, len(payload), size)])


@pytest.mark.parametrize("list_first", [True, False])
def test_the_reader_keeps_the_fault_list_and_only_the_minutes_near_a_fault(
    tmp_path: Path, list_first: bool
) -> None:
    written = data.read_archive(
        _chunks(_archive(list_first=list_first)), tmp_path, "dataset1", minutes=1
    )
    names = [p.relative_to(tmp_path).as_posix() for p in written]
    assert names == ["dataset1/log/03_53.tsv.gz", "dataset1/fault_list.json"]
    assert sorted(p.name for p in (tmp_path / "dataset1" / "log").iterdir()) == ["03_53.tsv.gz"]
    [fault] = data.find_faults(tmp_path)
    assert fault.noted_at == FAULT_AT - 44  # the readable time, kept as listed
    split = data.windows(fault, tmp_path, minutes=1)
    assert split.after == ["2022-08-22T03:53:54.000000Z INFO frontend: request complete"]


def test_an_archive_without_a_fault_list_is_refused_and_leaves_no_marker(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no fault list"):
        data.read_archive(_chunks(_archive(with_list=False)), tmp_path, "dataset1", minutes=1)
    assert not (tmp_path / "dataset1" / data.FAULT_LIST).exists()


def _source() -> DataSource:
    return DataSource(
        name="nezha",
        kind="zenodo",
        record="7",
        files=["nezhadata.zip"],
        stream=Stream(reader="nezha-logs", keep=["dataset1.tar.xz"], minutes=1),
        license="x",
        citation="y",
        description="z",
    )


@respx.mock
def test_the_download_streams_each_archive_once_and_keeps_no_zip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aria.data import download as dl

    monkeypatch.setattr(dl.ZENODO, "sleep", lambda _: None)
    payload = _zip_bytes({"dataset1.tar.xz": _archive(), "REDME.md": b"read me"})
    _zenodo_record("7", payload, "nezhadata.zip")
    route = respx.get("https://zenodo.org/f/7/nezhadata.zip").mock(side_effect=_ranged(payload))
    dest = download(_source(), tmp_path / "raw")
    assert (dest / "dataset1" / "log" / "03_53.tsv.gz").exists()
    assert (dest / "dataset1" / data.FAULT_LIST).exists()
    assert not (dest / "nezhadata.zip").exists()
    calls = route.call_count
    download(_source(), tmp_path / "raw")  # a day read to its end is not streamed again
    assert route.call_count == calls


@respx.mock
def test_an_archive_that_arrives_damaged_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aria.data import download as dl

    monkeypatch.setattr(dl.ZENODO, "sleep", lambda _: None)
    archive = _archive()
    payload = bytearray(_zip_bytes({"dataset1.tar.xz": archive}))
    payload[payload.index(archive) + len(archive) // 2] ^= 0xFF
    _zenodo_record("7", bytes(payload), "nezhadata.zip")
    respx.get("https://zenodo.org/f/7/nezhadata.zip").mock(side_effect=_ranged(bytes(payload)))
    with pytest.raises(DownloadError, match="could not be read"):
        download(_source(), tmp_path / "raw")
    assert not (tmp_path / "raw" / "nezha" / "dataset1" / data.FAULT_LIST).exists()


async def test_each_window_is_triaged_end_to_end_without_its_label(tmp_path: Path) -> None:
    root = _dataset(tmp_path / "nezha")
    builder = ScenarioBuilder(LinePools.from_loghub(LOGHUB))
    with tempfile.TemporaryDirectory() as tmp:
        env = await pl.EvalEnvironment.create(builder, db_path=Path(tmp) / "e.db")
        try:
            rows = await suite.triage(env, None, root)
        finally:
            await env.aclose()
    # The second fault's minutes are not in the excerpt, so it gives no windows.
    assert [(r["index"], r["window"]) for r in rows] == [(0, "healthy"), (0, "faulty")]
    assert all(r["severity"] in {"SEV1", "SEV2", "SEV3", "SEV4"} for r in rows)
    healthy, faulty = rows
    assert (faulty["service"], faulty["fault"], faulty["times_apart_s"]) == (
        "frontend",
        "exception",
        0.0,
    )
    assert healthy["error_lines"] == 0
    assert faulty["error_lines"] == 2  # the frontend's failed order, logged twice
    assert faulty["rank_most_errors"] == 1


def test_the_download_keeps_every_minute_the_suite_reads() -> None:
    stream = load_manifest().sources["nezha"].stream
    assert stream is not None
    assert stream.reader == "nezha-logs"
    assert (stream.minutes or 0) >= suite.WINDOW_MIN


def _row(case: str, window: str, severity: str, apart: float = 0.0) -> dict[str, Any]:
    return {
        "index": 0,
        "case": case,
        "system": "OB",
        "day": "2022-08-22",
        "service": "frontend",
        "fault": "cpu_contention",
        "times_apart_s": apart,
        "window": window,
        "faulty": window == "faulty",
        "lines": 25_000,
        "containers": 4,
        "error_lines": 0,
        "rank": 1 if window == "faulty" else None,
        "rank_most_errors": None,
        "rank_most_changed": 2,
        "severity": severity,
        "flagged": severity != "SEV4",
        "paged": severity in ("SEV1", "SEV2"),
        "needs_review": False,
        "severe_probability": 0.2 if window == "faulty" else 0.1,
        "leading_mode": "none",
        "candidates": ["frontend"],
    }


def test_the_summary_reads_like_rcaevals_with_nezhas_source() -> None:
    rows = [
        _row("a", "faulty", "SEV3"),
        _row("a", "healthy", "SEV4"),
        _row("b", "faulty", "SEV3", apart=60.0),
        _row("b", "healthy", "SEV3", apart=60.0),
    ]
    summary = suite.summarize(rows)
    assert summary["source"].startswith("Nezha's Online Boutique data")
    assert summary["days"] == ["2022-08-22"]
    assert summary["window_min"] == suite.WINDOW_MIN
    assert summary["times_disagree"] == 1
    assert summary["windows_over_line_cap"] == len(rows)
    assert summary["aria"]["paired"] == {"higher": 1, "same": 1, "lower": 0}
    assert summary["aria"]["naming"]["top1"]["hits"] == 2
    text = "\n".join(report_domains._nezha(summary))
    assert "### Faults injected into a shop's pods" in text
    assert "cpu contention" in text
    assert "the minute before it and of the minute from it on" in text
    assert "For 1 of the faults the fault list's timestamp and its readable time differ" in text
    assert suite.summarize([]) == suite.MISSING
    assert report_domains._nezha(suite.MISSING)[2].startswith("No results: download it")
