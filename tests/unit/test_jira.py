"""The Public Jira Dataset: reading a mongodump archive, keeping a subset as it streams, and
scoring ARIA's ticket model against the priority people set."""

from __future__ import annotations

import gzip
import json
import struct
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from aria.data import jira, mongodump
from aria.evals import jira as suite
from aria.evals import report_domains

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "jira"
MODEL = Path(__file__).resolve().parents[2] / "models" / "severity_ticket.json"


# --- a tiny BSON writer, for building archives ----------------------------------------------


def _element(key: str, value: Any) -> bytes:
    name = key.encode() + b"\x00"
    if isinstance(value, bool):
        return b"\x08" + name + (b"\x01" if value else b"\x00")
    if isinstance(value, int):
        return b"\x10" + name + struct.pack("<i", value)
    if isinstance(value, float):
        return b"\x01" + name + struct.pack("<d", value)
    if isinstance(value, str):
        data = value.encode() + b"\x00"
        return b"\x02" + name + struct.pack("<i", len(data)) + data
    if isinstance(value, dict):
        return b"\x03" + name + bson(value)
    if isinstance(value, list):
        return b"\x04" + name + bson({str(i): v for i, v in enumerate(value)})
    if isinstance(value, datetime):
        return b"\x09" + name + struct.pack("<q", int(value.timestamp() * 1000))
    if value is None:
        return b"\x0a" + name
    raise TypeError(type(value))


def bson(document: dict[str, Any]) -> bytes:
    body = b"".join(_element(k, v) for k, v in document.items()) + b"\x00"
    return struct.pack("<i", len(body) + 4) + body


def archive(blocks: list[tuple[str, list[dict[str, Any]]]], *, gzipped: bool = True) -> bytes:
    """A mongodump --archive stream: prelude, then each block's namespace header and documents."""
    end = struct.pack("<i", -1)
    names = sorted({name for name, _ in blocks})
    out = mongodump.MAGIC + bson({"concurrent_collections": 2, "version": "0.1"})
    out += b"".join(bson({"db": "JiraReposAnon", "collection": n}) for n in names) + end
    for name, docs in blocks:
        out += bson({"db": "JiraReposAnon", "collection": name, "EOF": False})
        out += b"".join(bson(d) for d in docs) + end
    for name in names:
        out += bson({"db": "JiraReposAnon", "collection": name, "EOF": True}) + end
    return gzip.compress(out, mtime=0) if gzipped else out


def issue(key: str, priority: str | None, *, changed_from: str | None = None) -> dict[str, Any]:
    histories = []
    if changed_from is not None:
        histories = [
            {
                "created": "2021-01-02T00:00:00.000+0000",
                "items": [{"field": "priority", "fromString": changed_from, "toString": priority}],
            },
            {"created": "2021-01-01T00:00:00.000+0000", "items": [{"field": "labels"}]},
        ]
    return {
        "key": key,
        "fields": {
            "summary": f"Issue {key}",
            "description": "x" * 3_000,
            "priority": {"name": priority} if priority else None,
            "issuetype": {"name": "Bug"},
            "project": {"key": key.split("-", maxsplit=1)[0], "name": "Project"},
            "components": [{"name": "core"}, {"name": "ui"}],
            "created": "2021-01-01T00:00:00.000+0000",
        },
        "changelog": {"histories": histories},
    }


def _chunks(data: bytes, size: int) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


# --- the archive reader ----------------------------------------------------------------------


@pytest.mark.parametrize("gzipped", [True, False])
@pytest.mark.parametrize("size", [1, 7, 4096])
def test_archive_documents_come_out_with_their_collection_whatever_the_chunking(
    gzipped: bool, size: int
) -> None:
    data = archive(
        [("Apache", [issue("A-1", "Major")]), ("Jira", [issue("J-1", "Low")])],
        gzipped=gzipped,
    )
    found = list(mongodump.documents(_chunks(data, size)))
    assert [name for name, _ in found] == ["Apache", "Jira"]
    doc, end = mongodump.decode(found[0][1])
    assert end == len(found[0][1])
    assert doc["key"] == "A-1"
    assert doc["fields"]["components"] == [{"name": "core"}, {"name": "ui"}]
    assert doc["fields"]["priority"] == {"name": "Major"}


def test_bson_values_of_every_common_type_decode() -> None:
    when = datetime(2021, 1, 1, tzinfo=UTC)
    doc, _ = mongodump.decode(bson({"n": 3, "f": 1.5, "b": True, "t": when, "z": None}))
    assert doc == {"n": 3, "f": 1.5, "b": True, "t": when, "z": None}


@pytest.mark.parametrize(
    "data",
    [
        b"\x05\x00\x00\x00",  # shorter than its own length says
        struct.pack("<i", 6) + b"\x63k\x00\x00",  # an unknown type
        struct.pack("<i", 9) + b"\x02k\x00" + struct.pack("<i", 99) + b"",  # a string overrun
    ],
)
def test_malformed_bson_is_refused(data: bytes) -> None:
    with pytest.raises(mongodump.ArchiveError):
        mongodump.decode(data)


def test_a_stream_that_is_not_an_archive_is_refused() -> None:
    with pytest.raises(mongodump.ArchiveError, match="not a mongodump archive"):
        list(mongodump.documents([b"PK\x03\x04 not an archive"]))


# --- the subset --------------------------------------------------------------------------------


def test_issue_records_keep_open_time_fields_and_the_priority_they_opened_with() -> None:
    record = jira.issue_record("Apache", issue("A-1", "Blocker", changed_from="Major"))
    assert record["priority"] == "Blocker"
    assert record["priority_at_open"] == "Major"  # the first priority change's "from"
    assert record["project"] == "A"
    assert record["components"] == ["core", "ui"]
    assert len(record["description"]) == jira.MAX_TEXT
    unchanged = jira.issue_record("Jira", issue("J-1", "Low"))
    assert unchanged["priority_at_open"] == "Low"
    assert jira.issue_record("Jira", issue("J-2", None))["priority"] == ""


def test_the_subset_keeps_the_first_issues_of_each_kept_instance_and_stops_reading() -> None:
    blocks = [
        ("Apache", [issue(f"A-{i}", "Major") for i in range(3)]),
        ("Other", [issue("O-1", "Major")]),
        ("Jira", [issue(f"J-{i}", "Low") for i in range(3)]),
        ("Apache", [issue("A-9", "Minor")]),
    ]
    seen: list[str] = []

    def documents() -> Any:
        for name, raw in mongodump.documents([archive(blocks)]):
            seen.append(name)
            yield name, raw

    kept = jira.select(documents(), ["Apache", "Jira"], limit=2)
    assert [r["key"] for r in kept["Apache"]] == ["A-0", "A-1"]
    assert [r["key"] for r in kept["Jira"]] == ["J-0", "J-1"]
    assert "A-9" not in json.dumps(kept)
    assert len(seen) == 6  # reading stopped once both instances had two issues


def test_subset_files_are_identical_on_every_write(tmp_path: Path) -> None:
    rows = [jira.issue_record("Apache", issue("A-1", "Major"))]
    jira.write_jsonl(tmp_path / "a.jsonl", rows)
    first = (tmp_path / "a.jsonl").read_bytes()
    jira.write_jsonl(tmp_path / "a.jsonl", rows)
    assert (tmp_path / "a.jsonl").read_bytes() == first


def _subset(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for path in FIXTURES.glob("*.jsonl"):
        (root / path.name).write_bytes(path.read_bytes())
    return root


def test_the_fixture_subset_reads_back_with_each_instances_levels(tmp_path: Path) -> None:
    issues = jira.read_issues(_subset(tmp_path / "jira"))
    assert {i.instance for i in issues} == {"Apache", "Jira"}
    levels = {(i.instance, i.priority): i.level for i in issues}
    assert levels[("Apache", "Critical")] == "2"
    assert levels[("Jira", "High")] == "2"
    assert levels[("Jira", "")] is None  # a suggestion with no priority is not scored
    changed = next(i for i in issues if i.priority_at_open != i.priority)
    assert changed.level_at_open != changed.level
    assert all(i.created is not None for i in issues)


# --- the suite ---------------------------------------------------------------------------------


def _issue(instance: str, key: str, priority: str, day: int, kind: str = "Bug") -> jira.Issue:
    return jira.Issue(
        instance=instance,
        key=key,
        project=key.split("-", maxsplit=1)[0],
        issue_type=kind,
        priority=priority,
        priority_at_open=priority,
        created=datetime(2021, 1, day, tzinfo=UTC),
        summary="s",
        description="d",
        components=(),
    )


def test_issues_split_by_time_within_each_instance() -> None:
    issues = [_issue("Apache", f"A-{d}", "Major", d) for d in range(1, 11)]
    issues += [_issue("Jira", f"J-{d}", "Low", d) for d in range(1, 11)]
    issues.append(_issue("Jira", "J-99", "", 20))  # no level: never scored
    reference, test = suite.split(issues)
    assert len(reference) == 14
    assert len(test) == 6
    assert max(i.created for i in reference if i.instance == "Apache") < min(  # type: ignore[type-var]
        i.created for i in test if i.instance == "Apache"
    )


def test_ticket_scores_count_urgent_tickets_rated_low_with_an_upper_bound() -> None:
    scores = suite._scores(["1", "2", "3", "4"], ["3", "2", "3", "4"])
    assert scores["accuracy"] == 0.75
    assert scores["urgent_missed"]["hits"] == 1
    assert scores["urgent_missed"]["of"] == 2
    assert scores["urgent_missed"]["upper95"] > 0.5


def test_the_suite_scores_the_ticket_model_and_its_baselines_on_the_fixtures(
    tmp_path: Path,
) -> None:
    summary, rows = suite.evaluate(_subset(tmp_path / "jira"), MODEL)
    assert summary["test_tickets"] == len(rows) > 0
    assert set(summary["pooled"]["methods"]) == set(suite.METHODS)
    assert summary["decided_by"] == {"model": len(rows)}  # Jira has no impact or urgency
    assert {r["truth"] for r in rows} <= {"1", "2", "3", "4"}
    text = "\n".join(report_domains._jira(summary))
    assert "### Ticket priority in public issue trackers" in text
    assert "| ARIA's ticket model |" in text


def test_the_suite_says_how_to_get_what_is_missing(tmp_path: Path) -> None:
    assert "missing" in suite.evaluate(tmp_path / "none")[0]
    root = _subset(tmp_path / "jira")
    assert "aria train tickets" in suite.evaluate(root, tmp_path / "no-model.json")[0]["missing"]
