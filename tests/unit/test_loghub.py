from __future__ import annotations

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
        assert back.level == rec.level
        if rec.ts is not None:
            assert back.ts is not None
            assert abs((back.ts - rec.ts).total_seconds()) < 1


def test_bgl_alert_tags_are_kept_as_labels() -> None:
    records = list(iter_structured_csv("bgl", FIXTURES / "BGL" / "BGL_2k.log_structured.csv"))
    tags = {r.label for r in records if r.label}
    assert {"KERNDTLB", "KERNSTOR", "KERNRTSP"} <= tags
    assert all(r.ts is not None and r.ts.tzinfo is UTC for r in records)


def test_unknown_system_falls_back_to_generic_parsing() -> None:
    rec = parse_raw_line("payments", "2026-03-02T10:15:00Z ERROR [api.gateway]: upstream timed out")
    assert rec.level == "ERROR"
    assert rec.component == "api.gateway"
    assert rec.message == "upstream timed out"
    assert rec.ts == datetime(2026, 3, 2, 10, 15, tzinfo=UTC)


def test_generic_parser_derives_level_from_message() -> None:
    assert parse_generic_line("svc", "kernel panic - not syncing").level == "FATAL"
    assert parse_generic_line("svc", "connection refused by peer").level == "ERROR"
    assert parse_generic_line("svc", "all good").level == "INFO"


@given(st.text(min_size=0, max_size=400))
def test_parsers_never_raise_on_arbitrary_input(line: str) -> None:
    for system in SYSTEMS:
        rec = parse_raw_line(system, line)
        assert isinstance(rec.message, str)
