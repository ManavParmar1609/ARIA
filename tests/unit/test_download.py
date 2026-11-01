from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from aria.data.download import DownloadError, compress_files, download
from aria.data.manifest import DataSource, Mirror, load_manifest


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


def test_repo_manifest_is_valid_and_pins_git_commits() -> None:
    manifest = load_manifest()
    for source in manifest.sources.values():
        assert source.license
        assert source.citation
        if source.kind == "git":
            assert source.commit is not None
            assert len(source.commit) == 40
        for mirror in source.mirrors:
            # A mirror on GitHub names a commit, so the copy cannot change under the same URL.
            if "githubusercontent.com" in mirror.url:
                assert len(mirror.url.split("/")[5]) == 40, mirror.url


@respx.mock
def test_zenodo_download_verifies_md5(tmp_path: Path) -> None:
    payload = _zip_bytes({"BGL.log": b"- 1117838570 2005.06.03 R02 ... hello\n"})
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    respx.get("https://zenodo.org/api/records/1").mock(
        return_value=httpx.Response(
            200,
            json={
                "files": [
                    {
                        "key": "BGL.zip",
                        "checksum": f"md5:{md5}",
                        "links": {"self": "https://zenodo.org/f/BGL.zip"},
                    }
                ]
            },
        )
    )
    respx.get("https://zenodo.org/f/BGL.zip").mock(
        return_value=httpx.Response(200, content=payload)
    )
    source = DataSource(
        name="bgl",
        kind="zenodo",
        record="1",
        files=["BGL.zip"],
        license="x",
        citation="y",
        description="z",
    )
    dest = download(source, tmp_path / "raw")
    assert (dest / "BGL.log").read_bytes().startswith(b"- 1117838570")


@respx.mock
def test_zenodo_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    respx.get("https://zenodo.org/api/records/2").mock(
        return_value=httpx.Response(
            200,
            json={
                "files": [
                    {
                        "key": "BGL.zip",
                        "checksum": "md5:deadbeef",
                        "links": {"self": "https://zenodo.org/f/x.zip"},
                    }
                ]
            },
        )
    )
    respx.get("https://zenodo.org/f/x.zip").mock(
        return_value=httpx.Response(200, content=_zip_bytes({"a": b"b"}))
    )
    source = DataSource(
        name="bgl",
        kind="zenodo",
        record="2",
        files=["BGL.zip"],
        license="x",
        citation="y",
        description="z",
    )
    with pytest.raises(DownloadError, match="mismatch"):
        download(source, tmp_path / "raw")
    assert not (tmp_path / "raw" / "bgl" / "BGL.zip").exists()


@respx.mock
def test_http_download_pins_checksum_on_first_use_then_enforces_it(tmp_path: Path) -> None:
    good = _zip_bytes({"incident_event_log.csv": b"number\nINC1\n"})
    route = respx.get("https://example.test/data.zip").mock(
        return_value=httpx.Response(200, content=good)
    )
    source = DataSource(
        name="uci",
        kind="http",
        url="https://example.test/data.zip",
        license="x",
        citation="y",
        description="z",
    )
    raw = tmp_path / "raw"
    download(source, raw)
    lock = json.loads((tmp_path / "checksums.lock").read_text())
    assert lock["uci"] == hashlib.sha256(good).hexdigest()

    (raw / "uci" / "data.zip").unlink()
    route.mock(return_value=httpx.Response(200, content=_zip_bytes({"evil.csv": b"tampered"})))
    with pytest.raises(DownloadError, match="sha256 mismatch"):
        download(source, raw)


@respx.mock
def test_zip_slip_is_refused(tmp_path: Path) -> None:
    evil = _zip_bytes({"../../escape.txt": b"nope"})
    respx.get("https://example.test/evil.zip").mock(return_value=httpx.Response(200, content=evil))
    source = DataSource(
        name="evil",
        kind="http",
        url="https://example.test/evil.zip",
        license="x",
        citation="y",
        description="z",
    )
    with pytest.raises(DownloadError, match="outside"):
        download(source, tmp_path / "raw")
    assert not (tmp_path / "escape.txt").exists()


def test_failed_download_leaves_no_empty_directory(tmp_path: Path) -> None:
    source = DataSource(name="nothing", kind="git", license="x", citation="y", description="z")
    with pytest.raises(DownloadError):
        download(source, tmp_path / "raw")
    assert not (tmp_path / "raw" / "nothing").exists()


@respx.mock
def test_a_mirror_stands_in_when_the_source_host_is_blocked(tmp_path: Path) -> None:
    log = b"- 1117838570 2005.06.03 R02-M1-N0 RAS KERNEL INFO hello\n"
    packed = gzip.compress(log)
    respx.get("https://zenodo.org/api/records/3").mock(return_value=httpx.Response(403))
    respx.get("https://mirror.test/BGL.log.gz").mock(
        return_value=httpx.Response(200, content=packed)
    )
    source = DataSource(
        name="bgl",
        kind="zenodo",
        record="3",
        files=["BGL.zip"],
        mirrors=[Mirror(url="https://mirror.test/BGL.log.gz", sha256=_sha(packed))],
        license="x",
        citation="y",
        description="z",
    )
    dest = download(source, tmp_path / "raw")
    assert (dest / "BGL.log").read_bytes() == log


@respx.mock
def test_a_mirror_serving_other_bytes_is_passed_over_for_the_next(tmp_path: Path) -> None:
    good = _zip_bytes({"incident_event_log.csv": b"number\nINC1\n"})
    respx.get("https://archive.test/data.zip").mock(side_effect=httpx.ConnectError("blocked"))
    respx.get("https://one.test/data%2Bcopy.zip").mock(
        return_value=httpx.Response(200, content=_zip_bytes({"evil.csv": b"tampered"}))
    )
    respx.get("https://two.test/data.zip").mock(return_value=httpx.Response(200, content=good))
    source = DataSource(
        name="uci",
        kind="http",
        url="https://archive.test/data.zip",
        sha256=_sha(good),
        mirrors=[
            Mirror(url="https://one.test/data%2Bcopy.zip", sha256=_sha(good)),
            Mirror(url="https://two.test/data.zip", sha256=_sha(good)),
        ],
        license="x",
        citation="y",
        description="z",
    )
    dest = download(source, tmp_path / "raw")
    assert (dest / "incident_event_log.csv").read_bytes() == b"number\nINC1\n"
    assert not (dest / "evil.csv").exists()
    assert not (dest / "data+copy.zip").exists()  # the mismatching copy is deleted


@respx.mock
def test_every_mirror_failing_names_each_failure(tmp_path: Path) -> None:
    respx.get("https://archive.test/data.zip").mock(return_value=httpx.Response(404))
    respx.get("https://one.test/data.zip").mock(return_value=httpx.Response(500))
    source = DataSource(
        name="uci",
        kind="http",
        url="https://archive.test/data.zip",
        sha256="0" * 64,
        mirrors=[Mirror(url="https://one.test/data.zip", sha256="0" * 64)],
        license="x",
        citation="y",
        description="z",
    )
    with pytest.raises(DownloadError, match=r"no mirror could be used .*one\.test.*500"):
        download(source, tmp_path / "raw")


def test_a_mirror_needs_a_full_sha256() -> None:
    with pytest.raises(ValueError, match="sha256"):
        Mirror(url="https://one.test/data.zip", sha256="abc")


@respx.mock
def test_tar_archives_cannot_write_outside_the_source_directory(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as bundle:
        data = b"nope"
        info = tarfile.TarInfo("../../escape.txt")
        info.size = len(data)
        bundle.addfile(info, io.BytesIO(data))
    payload = buffer.getvalue()
    respx.get("https://example.test/evil.tar.gz").mock(
        return_value=httpx.Response(200, content=payload)
    )
    source = DataSource(
        name="evil",
        kind="http",
        url="https://example.test/evil.tar.gz",
        sha256=_sha(payload),
        license="x",
        citation="y",
        description="z",
    )
    with pytest.raises(tarfile.OutsideDestinationError):
        download(source, tmp_path / "raw")
    assert not (tmp_path / "escape.txt").exists()


@respx.mock
def test_a_gitlab_source_pages_through_the_api_and_records_its_snapshot(tmp_path: Path) -> None:
    url = "https://gitlab.test/api/v4/projects/1/issues"
    pages = {
        "1": [{"iid": 2, "title": "b", "labels": ["incident"], "extra": "dropped"}],
        "2": [{"iid": 1, "title": "a", "labels": ["incident", "severity::2"]}],
        "3": [],
    }
    route = respx.get(url).mock(
        side_effect=lambda request: httpx.Response(200, json=pages[request.url.params["page"]])
    )
    source = DataSource(
        name="gitlab",
        kind="gitlab",
        url=url,
        params={"labels": "incident", "created_before": "2026-10-01T00:00:00Z"},
        license="x",
        citation="y",
        description="z",
    )
    dest = download(source, tmp_path / "raw")
    issues = json.loads((dest / "issues.json").read_text())
    assert [i["iid"] for i in issues] == [1, 2]  # sorted, so the snapshot hashes the same way
    assert "extra" not in issues[0]
    snapshot = json.loads((dest / "snapshot.json").read_text())
    assert snapshot["issues"] == 2
    assert snapshot["sha256"] == _sha((dest / "issues.json").read_bytes())
    assert route.calls[0].request.url.params["created_before"] == "2026-10-01T00:00:00Z"

    calls = route.call_count
    download(source, tmp_path / "raw")  # the same query is not fetched again
    assert route.call_count == calls


@respx.mock
def test_a_gitlab_page_that_fails_stops_the_download(tmp_path: Path) -> None:
    url = "https://gitlab.test/api/v4/projects/1/issues"
    respx.get(url).mock(return_value=httpx.Response(429))
    source = DataSource(
        name="gitlab", kind="gitlab", url=url, license="x", citation="y", description="z"
    )
    with pytest.raises(DownloadError, match="page 1 returned 429"):
        download(source, tmp_path / "raw")


def test_large_text_logs_are_stored_gzipped_one_file_at_a_time(tmp_path: Path) -> None:
    logs = tmp_path / "Nova" / "Test_1" / "logs" / "round_1" / "nova"
    logs.mkdir(parents=True)
    (logs / "nova-api.log.bzip2.out").write_text("2018-06-26 03:21:12.936 1 INFO nova.api x\n")
    (tmp_path / "nova.tsv").write_text("TEST\tROUND_1\n")
    assert compress_files(tmp_path, ["*.log.bzip2.out"]) == 1
    assert not (logs / "nova-api.log.bzip2.out").exists()
    with gzip.open(logs / "nova-api.log.bzip2.out.gz", "rt", encoding="utf-8") as handle:
        assert handle.read().startswith("2018-06-26 03:21:12.936")
    assert (tmp_path / "nova.tsv").exists()  # only what matches is compressed


# --- throttling, pinned checksums, the Hub and streamed subsets -------------------------------


@pytest.fixture(autouse=True)
def pauses(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record the pauses the downloader asks for instead of sleeping through them."""
    from aria.data import download as dl

    pauses: list[float] = []
    monkeypatch.setattr(dl.ZENODO, "sleep", pauses.append)
    monkeypatch.setattr(dl.TRANSPORT, "sleep", pauses.append)
    return pauses


def test_a_throttle_spaces_calls_and_backs_off_before_each_retry() -> None:
    from aria.data.download import Throttle

    now = [100.0]
    pauses: list[float] = []
    throttle = Throttle(interval=3.0, backoff=(15.0, 45.0))
    throttle.clock = lambda: now[0]
    throttle.sleep = pauses.append
    throttle.wait()
    now[0] += 1.0
    throttle.wait()
    assert pauses == [2.0]  # three seconds after the previous call, not one
    assert throttle.pause(0, None)
    assert throttle.pause(1, "60")
    assert pauses[1:] == [15.0, 60.0]  # a Retry-After longer than the backoff wins
    assert not throttle.pause(2, None)  # the retries are spent


def _zenodo_record(record: str, payload: bytes, name: str = "data.zip") -> None:
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    respx.get(f"https://zenodo.org/api/records/{record}").mock(
        return_value=httpx.Response(
            200,
            json={
                "files": [
                    {
                        "key": name,
                        "checksum": f"md5:{md5}",
                        "links": {"self": f"https://zenodo.org/f/{record}/{name}"},
                    }
                ]
            },
        )
    )


def _source(**fields: Any) -> DataSource:
    return DataSource(license="x", citation="y", description="z", **fields)


@respx.mock
def test_zenodo_limiting_this_callers_traffic_is_waited_out(
    tmp_path: Path, pauses: list[float]
) -> None:
    payload = b"labels\n"
    md5 = hashlib.md5(payload, usedforsecurity=False).hexdigest()
    record = {
        "files": [
            {"key": "a.csv", "checksum": f"md5:{md5}", "links": {"self": "https://zenodo.org/f/a"}}
        ]
    }
    api = respx.get("https://zenodo.org/api/records/7").mock(
        side_effect=[
            httpx.Response(403, text="Access restricted due to unusual traffic"),
            httpx.Response(200, json=record),
        ]
    )
    respx.get("https://zenodo.org/f/a").mock(return_value=httpx.Response(200, content=payload))
    dest = download(_source(name="a", kind="zenodo", record="7", files=["a.csv"]), tmp_path)
    assert (dest / "a.csv").read_bytes() == payload
    assert api.call_count == 2
    assert 15.0 in pauses


@respx.mock
def test_a_record_whose_published_checksum_moved_from_the_pin_is_refused(tmp_path: Path) -> None:
    _zenodo_record("8", b"new bytes")
    source = _source(
        name="pinned",
        kind="zenodo",
        record="8",
        files=["data.zip"],
        checksums={"data.zip": "md5:" + "0" * 32},
    )
    with pytest.raises(DownloadError, match="the record's files changed"):
        download(source, tmp_path / "raw")


@respx.mock
def test_a_file_that_misses_its_pinned_sha256_is_deleted(tmp_path: Path) -> None:
    payload = _zip_bytes({"a.txt": b"a"})
    _zenodo_record("9", payload)
    respx.get("https://zenodo.org/f/9/data.zip").mock(
        return_value=httpx.Response(200, content=payload)
    )
    source = _source(
        name="pinned",
        kind="zenodo",
        record="9",
        files=["data.zip"],
        extract=False,
        checksums={"data.zip": "sha256:" + "0" * 64},
    )
    with pytest.raises(DownloadError, match="sha256 mismatch"):
        download(source, tmp_path / "raw")
    assert not (tmp_path / "raw" / "pinned" / "data.zip").exists()


def test_a_pinned_checksum_names_its_algorithm_and_full_digest() -> None:
    with pytest.raises(ValueError, match="md5:<32 hex>"):
        _source(name="x", kind="zenodo", checksums={"a": "crc32:1234"})


@respx.mock
def test_a_transfer_cut_off_part_way_is_retried(tmp_path: Path, pauses: list[float]) -> None:
    good = _zip_bytes({"incident_event_log.csv": b"number\nINC1\n"})
    route = respx.get("https://archive.test/data.zip").mock(
        side_effect=[httpx.ReadError("connection reset"), httpx.Response(200, content=good)]
    )
    source = _source(
        name="uci", kind="http", url="https://archive.test/data.zip", sha256=_sha(good)
    )
    dest = download(source, tmp_path / "raw")
    assert (dest / "incident_event_log.csv").exists()
    assert route.call_count == 2
    assert pauses == [2.0]


def _blob_id(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode()
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


@respx.mock
def test_hub_files_are_checked_against_the_hash_the_hub_records(tmp_path: Path) -> None:
    commit = "a" * 40
    small, large = b"fault: x\n", b"time\tline\n" * 50
    listing = [
        {"type": "directory", "path": "snapshots/s1"},
        {"type": "file", "path": "snapshots/s1/ground_truth.yaml", "oid": _blob_id(small)},
        {"type": "file", "path": "snapshots/s1/events.tsv", "lfs": {"oid": _sha(large)}},
        {"type": "file", "path": "snapshots/s1/metrics.tsv", "oid": "f" * 40},
    ]
    respx.get(url__regex=rf"https://huggingface\.co/api/datasets/org/set/tree/{commit}/.*").mock(
        return_value=httpx.Response(200, json=listing)
    )
    base = f"https://huggingface.co/datasets/org/set/resolve/{commit}/snapshots/s1"
    respx.get(f"{base}/ground_truth.yaml").mock(return_value=httpx.Response(200, content=small))
    events = respx.get(f"{base}/events.tsv").mock(return_value=httpx.Response(200, content=large))
    source = _source(
        name="hub",
        kind="huggingface",
        url="https://huggingface.co/datasets/org/set",
        commit=commit,
        paths=["snapshots/*/ground_truth.yaml", "snapshots/*/events.tsv"],
    )
    dest = download(source, tmp_path / "raw")
    assert (dest / "snapshots/s1/ground_truth.yaml").read_bytes() == small
    assert (dest / "snapshots/s1/events.tsv").read_bytes() == large
    assert not (dest / "snapshots/s1/metrics.tsv").exists()  # no pattern asks for it
    assert (dest / ".commit").read_text().strip() == commit

    download(source, tmp_path / "raw")  # files already verified are not fetched again
    assert events.call_count == 1
    (dest / "snapshots/s1/events.tsv").unlink()
    events.mock(return_value=httpx.Response(200, content=b"tampered"))
    with pytest.raises(DownloadError, match="does not match the Hub's hash"):
        download(source, tmp_path / "raw")


def _ranged(payload: bytes) -> Any:
    """A server that answers HTTP range requests for ``payload``."""

    def answer(request: httpx.Request) -> httpx.Response:
        first, _, last = request.headers["Range"].removeprefix("bytes=").partition("-")
        start, end = int(first), min(int(last or len(payload) - 1), len(payload) - 1)
        return httpx.Response(
            206,
            content=payload[start : end + 1],
            headers={"content-range": f"bytes {start}-{end}/{len(payload)}"},
        )

    return answer


@respx.mock
def test_a_streamed_source_keeps_its_subset_without_storing_the_whole_zip(
    tmp_path: Path,
) -> None:
    from test_jira import archive, issue

    from aria.data.manifest import Stream

    member = "Data/dump.archive"
    dump = archive([("Apache", [issue("A-1", "Major"), issue("A-2", "Minor")])])
    payload = _zip_bytes({"Data/README.md": b"read me", member: dump})
    _zenodo_record("10", payload, "big.zip")
    respx.get("https://zenodo.org/f/10/big.zip").mock(side_effect=_ranged(payload))
    source = _source(
        name="jira",
        kind="zenodo",
        record="10",
        files=["big.zip"],
        stream=Stream(reader="jira-mongodump", member=member, keep=["Apache"], limit=1),
    )
    dest = download(source, tmp_path / "raw")
    assert not (dest / "big.zip").exists()  # the zip itself is never stored
    with (dest / "apache.jsonl").open() as handle:
        assert [json.loads(line)["key"] for line in handle] == ["A-1"]

    pinned = source.model_copy(update={"checksums": {"apache.jsonl": "sha256:" + "0" * 64}})
    with pytest.raises(DownloadError, match=r"apache\.jsonl sha256 mismatch"):
        download(pinned, tmp_path / "raw")


class _CutOff(httpx.SyncByteStream):
    """A response body that stops part way, as a reset connection does."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    def __iter__(self) -> Any:
        yield self.data
        raise httpx.ReadError("connection reset by peer")


def test_a_member_stream_cut_off_part_way_picks_up_where_it_stopped() -> None:
    from aria.data import remote_zip

    member_bytes = b"x" * 5_000 + b"y" * 5_000
    payload = _zip_bytes({"m.bin": member_bytes})
    answer = _ranged(payload)
    calls: list[str] = []
    cut = [False]

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(request.headers["Range"])
        response = answer(request)
        if cut[0]:  # the member's first read: cut it off after a few bytes
            cut[0] = False
            return httpx.Response(206, stream=_CutOff(response.content[:1_000]))
        return response

    with respx.mock, httpx.Client() as client:
        respx.get("https://files.test/a.zip").mock(side_effect=flaky)
        member = remote_zip.locate(client, "https://files.test/a.zip", "m.bin")
        cut[0] = True
        data = b"".join(remote_zip.stream(client, "https://files.test/a.zip", member))
    assert data == member_bytes
    first, resumed = calls[-2], calls[-1]
    assert (
        int(resumed.split("=")[1].split("-")[0]) == int(first.split("=")[1].split("-")[0]) + 1_000
    )


def test_a_member_whose_bytes_miss_the_zips_crc_is_refused() -> None:
    from aria.data import remote_zip

    member_bytes = b"every line of the day's logs\n" * 200
    payload = bytearray(_zip_bytes({"m.bin": member_bytes}))  # stored, so bytes map one to one
    payload[payload.index(b"every line") + 100] ^= 0x20
    with respx.mock, httpx.Client() as client:
        respx.get("https://files.test/a.zip").mock(side_effect=_ranged(bytes(payload)))
        member = remote_zip.locate(client, "https://files.test/a.zip", "m.bin")
        chunks = remote_zip.stream(client, "https://files.test/a.zip", member)
        with pytest.raises(remote_zip.RemoteZipError, match="CRC-32 mismatch"):
            b"".join(chunks)
