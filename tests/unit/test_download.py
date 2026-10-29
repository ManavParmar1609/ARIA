from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest
import respx

from aria.data.download import DownloadError, download
from aria.data.manifest import DataSource, load_manifest


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
