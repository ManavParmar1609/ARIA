"""Fetch and verify the datasets in the manifest.

Integrity checks per source kind:

* git: a pinned commit SHA is content-addressed, so the checkout is the checksum.
* zenodo: files are verified against the md5 Zenodo publishes for the record.
* uci / http: verified against a pinned sha256, or pinned on first download into
  ``data/checksums.lock`` (trust on first use) and verified on every later download.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any

import httpx

from aria.data.manifest import DataSource
from aria.observability.logging import get_logger

log = get_logger(__name__)
_CHUNK = 1 << 20
_TIMEOUT = httpx.Timeout(60.0, connect=20.0)


class DownloadError(RuntimeError):
    pass


def _hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stream_to(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    with (
        httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client,
        client.stream("GET", url) as response,
    ):
        if response.status_code != httpx.codes.OK:
            msg = f"GET {url} returned {response.status_code}"
            raise DownloadError(msg)
        with partial.open("wb") as handle:
            for chunk in response.iter_bytes(_CHUNK):
                handle.write(chunk)
    partial.replace(target)


def _git(args: list[str], cwd: Path) -> None:
    # Arguments are fixed strings from the manifest; no shell is involved.
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)  # noqa: S603, S607


def download_git(source: DataSource, dest: Path) -> Path:
    """Sparse, blob-filtered checkout of the pinned commit, copying only the listed paths."""
    if not (source.url and source.commit):
        msg = f"{source.name}: git sources need url and commit"
        raise DownloadError(msg)
    marker = dest / ".commit"
    if marker.exists() and marker.read_text().strip() == source.commit:
        log.info("dataset.cached", source=source.name, commit=source.commit[:12])
        return dest
    with tempfile.TemporaryDirectory(prefix=f"aria-{source.name}-") as tmp:
        work = Path(tmp)
        _git(["init", "-q"], work)
        _git(["remote", "add", "origin", source.url], work)
        _git(["sparse-checkout", "set", "--no-cone", *source.paths], work)
        _git(["fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", source.commit], work)
        _git(["checkout", "-q", "FETCH_HEAD"], work)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(work, dest, ignore=shutil.ignore_patterns(".git"))
    marker.write_text(source.commit + "\n")
    log.info("dataset.fetched", source=source.name, commit=source.commit[:12])
    return dest


def _zenodo_files(record: str) -> list[dict[str, Any]]:
    url = f"https://zenodo.org/api/records/{record}"
    response = httpx.get(url, timeout=_TIMEOUT, follow_redirects=True)
    if response.status_code != httpx.codes.OK:
        msg = f"Zenodo record {record} returned {response.status_code}"
        raise DownloadError(msg)
    files: list[dict[str, Any]] = response.json().get("files", [])
    return files


def download_zenodo(source: DataSource, dest: Path) -> Path:
    if not source.record:
        msg = f"{source.name}: zenodo sources need a record id"
        raise DownloadError(msg)
    available = {entry["key"]: entry for entry in _zenodo_files(source.record)}
    for name in source.files:
        entry = available.get(name)
        if entry is None:
            msg = f"{source.name}: {name} not found in Zenodo record {source.record}"
            raise DownloadError(msg)
        algorithm, _, expected = str(entry.get("checksum", "")).partition(":")
        target = dest / name
        if not (target.exists() and _hash_file(target, algorithm or "md5") == expected):
            _stream_to(entry["links"]["self"], target)
            actual = _hash_file(target, algorithm or "md5")
            if expected and actual != expected:
                target.unlink(missing_ok=True)
                msg = f"{name}: {algorithm} mismatch (expected {expected}, got {actual})"
                raise DownloadError(msg)
        _extract(target, dest)
    return dest


def _uci_data_url(dataset_id: int) -> str | None:
    try:
        response = httpx.get(
            "https://archive.ics.uci.edu/api/dataset",
            params={"id": dataset_id},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        if response.status_code == httpx.codes.OK:
            data = response.json().get("data", {})
            url = data.get("data_url")
            return str(url) if url else None
    except httpx.HTTPError:
        return None
    return None


def download_http(source: DataSource, dest: Path, lockfile: Path) -> Path:
    url = source.url
    if source.kind == "uci" and source.dataset_id is not None:
        url = _uci_data_url(source.dataset_id) or source.fallback_url
    if not url:
        msg = f"{source.name}: no download URL"
        raise DownloadError(msg)
    target = dest / Path(url.split("?", 1)[0]).name
    lock = json.loads(lockfile.read_text()) if lockfile.exists() else {}
    expected = source.sha256 or lock.get(source.name)
    if not (target.exists() and expected and _hash_file(target, "sha256") == expected):
        _stream_to(url, target)
    actual = _hash_file(target, "sha256")
    if expected and actual != expected:
        target.unlink(missing_ok=True)
        msg = f"{source.name}: sha256 mismatch (expected {expected}, got {actual})"
        raise DownloadError(msg)
    if not expected:
        lock[source.name] = actual
        lockfile.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
        log.info("dataset.checksum_pinned", source=source.name, sha256=actual)
    _extract(target, dest)
    return dest


def _extract(archive: Path, dest: Path) -> None:
    if archive.suffix != ".zip":
        return
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = (dest / member.filename).resolve()
            if not path.is_relative_to(dest.resolve()):  # zip-slip guard
                msg = f"refusing to extract {member.filename} outside {dest}"
                raise DownloadError(msg)
        bundle.extractall(dest)  # members were validated above
        nested = [m for m in bundle.namelist() if m.endswith(".zip")]
    for inner in nested:
        _extract(dest / inner, dest)


def download(source: DataSource, raw_dir: Path) -> Path:
    dest = raw_dir / source.name
    created = not dest.exists()
    dest.mkdir(parents=True, exist_ok=True)
    try:
        if source.kind == "git":
            return download_git(source, dest)
        if source.kind == "zenodo":
            return download_zenodo(source, dest)
        return download_http(source, dest, raw_dir.parent / "checksums.lock")
    except Exception:
        if created and not any(dest.iterdir()):
            dest.rmdir()  # leave no empty directory that would look like a downloaded source
        raise
