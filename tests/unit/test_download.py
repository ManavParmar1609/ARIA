from __future__ import annotations

import gzip
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path

import httpx
import pytest
import respx

from aria.data.download import DownloadError, download
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
