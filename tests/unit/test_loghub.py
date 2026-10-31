from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from aria.data.loghub import (
    LOGHUB_DIRS,
    SYSTEMS,
    format_raw_line,
    format_to_regex,
    iter_structured_csv,
    normalize_level,
    parse_generic_line,
    parse_raw_line,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"
FIXTURE_SYSTEMS = sorted(
    (directory, system)
    for directory, system in LOGHUB_DIRS.items()
    if (FIXTURES / directory / f"{directory}_2k.log_structured.csv").exists()
)


def test_format_to_regex_names_every_field() -> None:
    regex = format_to_regex("<Date> <Time> <Level> <Component>: <Content>")
    match = regex.match("2015-10-18 18:01:47,978 INFO org.apache.Foo: hello: world")
    assert match is not None
    assert match["Component"] == "org.apache.Foo"
    assert match["Content"] == "hello: world"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("SEVERE", "ERROR"), ("warning", "WARN"), ("FAILURE", "FATAL"), ("combo", None), (None, None)],
)
def test_normalize_level(raw: str | None, expected: str | None) -> None:
    assert normalize_level(raw) == expected


@pytest.mark.parametrize(("directory", "system"), FIXTURE_SYSTEMS)
def test_records_render_and_parse_back_exactly(directory: str, system: str) -> None:
    records = list(
        iter_structured_csv(system, FIXTURES / directory / f"{directory}_2k.log_structured.csv")
    )
    assert records, system
    for rec in records:
        back = parse_raw_line(system, format_raw_line(rec))
        assert back.message == rec.message
        assert (back.node or None) == (rec.node or None)
        assert (back.component or None) == (rec.component or None)
        assert back.level == rec.level
        if rec.ts is not None:
            assert back.ts is not None
            assert abs((back.ts - rec.ts).total_seconds()) < 1


@pytest.mark.parametrize(
    ("bracket", "thread", "component"),
    [
        (
            "SendWorker:188978561024:QuorumCnxManager$SendWorker@679",
            "SendWorker:188978561024",
            "QuorumCnxManager$SendWorker",
        ),
        (
            "QuorumPeer[myid=1]/0:0:0:0:0:0:0:0:2181:FastLeaderElection@774",
            "QuorumPeer[myid=1]/0:0:0:0:0:0:0:0:2181",
            "FastLeaderElection",
        ),
        (
            "ProcessThread(sid:2 cport:-1)::PrepRequestProcessor@476",
            "ProcessThread(sid:2 cport:-1)",
            "PrepRequestProcessor",
        ),
        ("main:QuorumPeerMain@127", "main", "QuorumPeerMain"),
    ],
)
def test_zookeeper_component_is_the_class_and_the_thread_keeps_its_colons(
    bracket: str, thread: str, component: str
) -> None:
    line = f"2015-07-29 19:04:29,071 - WARN  [{bracket}] - Interrupted while waiting for message"
    record = parse_raw_line("zookeeper", line)
    assert (record.node, record.component) == (thread, component)
    back = parse_raw_line("zookeeper", format_raw_line(record))
    assert (back.node, back.component) == (thread, component)


def test_bgl_alert_tags_are_kept_as_labels() -> None:
    records = list(iter_structured_csv("bgl", FIXTURES / "BGL" / "BGL_2k.log_structured.csv"))
    tags = {r.label for r in records if r.label}
    assert {"KERNDTLB", "KERNSTOR", "KERNRTSP"} <= tags
    assert all(r.ts is not None and r.ts.tzinfo is UTC for r in records)


def test_a_bgl_line_with_no_message_keeps_its_time_node_and_level() -> None:
    # 34,470 lines of the full BGL log end at the level; they once lost every header field.
    line = (
        "- 1120866514 2005.07.08 R02-M1-N8-C:J13-U01 2005-07-08-16.48.34.004234 "
        "R02-M1-N8-C:J13-U01 RAS KERNEL FATAL\n"
    )
    record = parse_raw_line("bgl", line)
    assert record.ts == datetime(2005, 7, 8, 23, 48, 34, tzinfo=UTC)
    assert record.node == "R02-M1-N8-C:J13-U01"
    assert record.level == "FATAL"
    assert record.message == ""
    # A separator other than spaces still needs its message: "Component:" alone is not a line.
    assert format_to_regex("<Component>: <Content>").match("kernel:") is None


def test_a_long_line_that_misses_its_format_is_rejected_at_once() -> None:
    # An indented dump or a wrapped warning in an OpenStack log has no header. With every field
    # free to hold spaces, matching tried each way of sharing its spaces among six fields, and
    # one such line took minutes.
    lines = [
        " " * 50 + "u'Network': u'1.0', " * 30,
        "limitations in Nova prior to the use of the Placement API. Now scheduling will " * 4,
    ]
    for line in lines:
        started = time.perf_counter()
        record = parse_raw_line("openstack", line)
        assert time.perf_counter() - started < 1.0
        assert record.message == line.strip()


@pytest.mark.parametrize(
    ("system", "line", "field", "value"),
    [
        (  # Fields between brackets or before another separator still hold spaces.
            "proxifier",
            "[10.30 16:51:56] svchost.exe *64 - proxy.cse.cuhk.edu.hk:5070 close, 303 bytes sent",
            "Program",
            "svchost.exe *64",
        ),
        (
            "hadoop",
            (
                "2015-10-18 18:05:54,325 INFO [IPC Server handler 5 on 62270] "
                "org.apache.hadoop.mapred.TaskAttemptListenerImpl: Ping from attempt_1"
            ),
            "Process",
            "IPC Server handler 5 on 62270",
        ),
        (
            "openstack",
            (
                "nova-api.log.1.2017-05-16_13:53:08 2017-05-16 00:00:00.008 25746 INFO "
                "nova.osapi_compute.wsgi.server [req-38101a0b-2096-447d-96ea-a692162415ae "
                "113d3a99c3da401fbd62cc2caa5b96d2 54fadb412c4e40cdbaed9335e4c35a9e - - -] "
                '10.11.10.1 "GET /v2/servers/detail HTTP/1.1" status: 200'
            ),
            "ADDR",
            (
                "req-38101a0b-2096-447d-96ea-a692162415ae 113d3a99c3da401fbd62cc2caa5b96d2 "
                "54fadb412c4e40cdbaed9335e4c35a9e - - -"
            ),
        ),
    ],
)
def test_fields_that_hold_spaces_keep_them(system: str, line: str, field: str, value: str) -> None:
    match = SYSTEMS[system].regex.match(line)
    assert match is not None
    assert match[field] == value


def test_unknown_system_falls_back_to_generic_parsing() -> None:
    rec = parse_raw_line("payments", "2026-03-02T10:15:00Z ERROR [api.gateway]: upstream timed out")
    assert rec.level == "ERROR"
    assert rec.component == "api.gateway"
    assert rec.message == "upstream timed out"
    assert rec.ts == datetime(2026, 3, 2, 10, 15, tzinfo=UTC)


@pytest.mark.parametrize(
    ("line", "when", "level", "component", "message"),
    [
        # Hadoop's compact time and a thread number before the level: a pasted WARN stays a WARN.
        (
            "081109 203807 222 WARN dfs.DataNode$DataXceiver: Got exception while serving",
            datetime(2008, 11, 9, 20, 38, 7, tzinfo=UTC),
            "WARN",
            "dfs.DataNode$DataXceiver",
            "Got exception while serving",
        ),
        # A Java logger's comma before the milliseconds, and a thread before the component.
        (
            "2026-10-31 10:00:01,250 ERROR [main] org.app.Server: connection refused",
            datetime(2026, 10, 31, 10, 0, 1, 250_000, tzinfo=UTC),
            "ERROR",
            "org.app.Server",
            "connection refused",
        ),
        (
            "2026/10/31 10:00:02 INFO worker: started",
            datetime(2026, 10, 31, 10, 0, 2, tzinfo=UTC),
            "INFO",
            "worker",
            "started",
        ),
    ],
)
def test_generic_parser_reads_common_timestamps_and_levels(
    line: str, when: datetime, level: str, component: str, message: str
) -> None:
    rec = parse_generic_line("svc", line)
    assert (rec.ts, rec.level, rec.component, rec.message) == (when, level, component, message)


def test_generic_parser_reads_syslog_times_and_keeps_a_lone_bracket_in_the_message() -> None:
    rec = parse_generic_line("svc", "Oct 31 10:00:01 host sshd[123]: Failed password for root")
    assert rec.ts is not None
    assert (rec.ts.month, rec.ts.day, rec.ts.hour, rec.ts.second) == (10, 31, 10, 1)
    assert rec.message == "host sshd[123]: Failed password for root"
    # A bracket that does not lead to a component is part of what the line says.
    tagged = parse_generic_line("svc", "[Controller id=1] Processing automatic rebalance")
    assert tagged.message == "[Controller id=1] Processing automatic rebalance"


def test_generic_parser_derives_level_from_message() -> None:
    assert parse_generic_line("svc", "kernel panic - not syncing").level == "FATAL"
    assert parse_generic_line("svc", "connection refused by peer").level == "ERROR"
    assert parse_generic_line("svc", "all good").level == "INFO"


@given(st.text(min_size=0, max_size=400))
def test_parsers_never_raise_on_arbitrary_input(line: str) -> None:
    for system in SYSTEMS:
        rec = parse_raw_line(system, line)
        assert isinstance(rec.message, str)
