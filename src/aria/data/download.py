"""Fetch and verify the datasets in the manifest.

Integrity checks per source kind:

* git: a pinned commit SHA is content-addressed, so the checkout is the checksum.
* zenodo: files are verified against the md5 Zenodo publishes for the record.
* uci / http: verified against a pinned sha256, or pinned on first download into
  ``data/checksums.lock`` (trust on first use) and verified on every later download.
* mirrors: when a source's own host cannot be reached (or serves other bytes), its listed
  mirrors are tried in order, each trusted only if its file matches the sha256 pinned beside it.
* gitlab: a live issues API, read page by page with fixed parameters. It cannot be pinned (an
  issue can be edited later), so the snapshot's sha256 and date are recorded beside it.
* huggingface: files of a dataset repository at a pinned commit, each verified against the hash
  the Hub records for it (the sha256 of a large file, the git blob id of a small one).
* checksums: pinned in the manifest beside a source. A Zenodo file must match its pin as well as
  the checksum the record publishes, so a record that changes its files is refused.
* stream: part of a file too large to keep is read as it arrives (``aria.data.remote_zip``) and
  only what the source's reader keeps is written; the manifest pins the checksums of those files.

Zenodo refuses bursts (HTTP 403 "unusual traffic" after about two dozen quick calls), so every
request to it waits ``ZENODO.interval`` seconds after the previous one, and a refused request is
retried after a growing pause.
"""

from __future__ import annotations

import fnmatch
import gzip
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import httpx

from aria.data.manifest import DataSource
from aria.observability.logging import get_logger

log = get_logger(__name__)
_CHUNK = 1 << 20
_TIMEOUT = httpx.Timeout(60.0, connect=20.0)


class DownloadError(RuntimeError):
    pass


class Throttle:
    """Spaces the requests sent to one host, and pauses before retrying a refused one."""

    def __init__(self, interval: float, backoff: tuple[float, ...]) -> None:
        self.interval = interval
        self.backoff = backoff
        self.sleep: Callable[[float], None] = time.sleep
        self.clock: Callable[[], float] = time.monotonic
        self._last: float | None = None

    def wait(self) -> None:
        """Return once ``interval`` seconds have passed since the previous request."""
        if self._last is not None:
            pause = self.interval - (self.clock() - self._last)
            if pause > 0:
                self.sleep(pause)
        self._last = self.clock()

    def pause(self, attempt: int, retry_after: str | None) -> bool:
        """Sleep before retry ``attempt`` (from 0); False once the retries are spent."""
        if attempt >= len(self.backoff):
            return False
        wait = self.backoff[attempt]
        if retry_after and retry_after.isdigit():
            wait = max(wait, float(retry_after))
        self.sleep(wait)
        return True


# Zenodo answered 403 after about two dozen quick calls; these spacings kept sessions clear.
ZENODO = Throttle(interval=3.0, backoff=(15.0, 45.0, 90.0))
# A transfer cut off mid-way (a reset connection, a TLS EOF) is retried after these pauses.
TRANSPORT = Throttle(interval=0.0, backoff=(2.0, 5.0))
_BUSY = {429, 502, 503, 504}


def throttle_for(url: str) -> Throttle | None:
    return ZENODO if urlsplit(url).hostname == "zenodo.org" else None


def _refused(status: int, body: bytes) -> bool:
    """A refusal worth waiting out: the host is busy, or it is limiting this caller's traffic
    (Zenodo's 403 says "unusual traffic"; a 403 for any other reason is final)."""
    return status in _BUSY or (status == httpx.codes.FORBIDDEN and b"unusual traffic" in body)


def _hash_file(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _get(client: httpx.Client, url: str) -> httpx.Response:
    """GET, spaced and retried when the host is one that refuses bursts."""
    throttle = throttle_for(url)
    attempt = 0
    while True:
        if throttle is not None:
            throttle.wait()
        response = client.get(url)
        if (
            throttle is None
            or not _refused(response.status_code, response.content)
            or not throttle.pause(attempt, response.headers.get("retry-after"))
        ):
            return response
        attempt += 1


def _fetch(client: httpx.Client, url: str) -> httpx.Response:
    """``_get``, with a connection cut off part way retried after a pause."""
    cuts = 0
    while True:
        try:
            return _get(client, url)
        except httpx.TransportError:
            if not TRANSPORT.pause(cuts, None):
                raise
            cuts += 1


def _stream_to(url: str, target: Path) -> None:
    """Download ``url`` to ``target``; a refusal worth waiting out, or a transfer cut off part
    way, is retried after a pause."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    throttle = throttle_for(url)
    refusals = cuts = 0
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        while True:
            if throttle is not None:
                throttle.wait()
            try:
                with client.stream("GET", url) as response:
                    status = response.status_code
                    if status == httpx.codes.OK:
                        with partial.open("wb") as handle:
                            for chunk in response.iter_bytes(_CHUNK):
                                handle.write(chunk)
                        break
                    body = response.read() if status == httpx.codes.FORBIDDEN else b""
                    retry_after = response.headers.get("retry-after")
            except httpx.TransportError:
                if not TRANSPORT.pause(cuts, None):
                    raise
                cuts += 1
                continue
            if not (
                throttle is not None
                and _refused(status, body)
                and throttle.pause(refusals, retry_after)
            ):
                msg = f"GET {url} returned {status}"
                raise DownloadError(msg)
            refusals += 1
    partial.replace(target)


def _check_pinned(source: DataSource, name: str, path: Path) -> None:
    """Refuse a file whose bytes differ from the checksum the manifest pins for it."""
    pinned = source.checksums.get(name)
    if pinned is None:
        return
    algorithm, _, expected = pinned.partition(":")
    actual = _hash_file(path, algorithm)
    if actual != expected:
        path.unlink(missing_ok=True)
        msg = f"{source.name}: {name} {algorithm} mismatch (pinned {expected}, got {actual})"
        raise DownloadError(msg)


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
        shutil.rmtree(work / ".git")  # the objects are not needed once the files are out
        compress_files(work, source.compress)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(work, dest)
    marker.write_text(source.commit + "\n")
    log.info("dataset.fetched", source=source.name, commit=source.commit[:12])
    return dest


def compress_files(root: Path, patterns: list[str]) -> int:
    """Gzip every file under ``root`` that matches one of ``patterns`` (``x`` becomes ``x.gz``),
    one at a time, so a large checkout never needs room for two copies of itself."""
    count = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if not any(path.match(pattern) for pattern in patterns):
            continue
        with path.open("rb") as src, gzip.open(path.with_name(path.name + ".gz"), "wb") as out:
            shutil.copyfileobj(src, out, _CHUNK)
        path.unlink()
        count += 1
    return count


def _zenodo_files(record: str) -> list[dict[str, Any]]:
    url = f"https://zenodo.org/api/records/{record}"
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        response = _fetch(client, url)
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
        published = str(entry.get("checksum", ""))
        pinned = source.checksums.get(name, "")
        same_kind = pinned.partition(":")[0] == published.partition(":")[0]
        if pinned and published and same_kind and pinned != published:
            msg = (
                f"{source.name}: Zenodo now publishes {published} for {name}, but the manifest "
                f"pins {pinned}; the record's files changed"
            )
            raise DownloadError(msg)
        if source.stream is not None:
            # Too large to keep: the reader takes what it needs as the file streams in.
            stream_source(source, dest, entry["links"]["self"])
            continue
        algorithm, _, expected = published.partition(":")
        target = dest / name
        if not (target.exists() and _hash_file(target, algorithm or "md5") == expected):
            _stream_to(entry["links"]["self"], target)
            actual = _hash_file(target, algorithm or "md5")
            if expected and actual != expected:
                target.unlink(missing_ok=True)
                msg = f"{name}: {algorithm} mismatch (expected {expected}, got {actual})"
                raise DownloadError(msg)
        _check_pinned(source, name, target)
        if source.extract:
            _extract(target, dest)
    return dest


# A stream reader: (source, destination, HTTP client, the file's URL when the source has one
# file) -> the files it wrote under the destination.
StreamReader = Callable[[DataSource, Path, httpx.Client, str | None], list[Path]]


def _stream_readers() -> dict[str, StreamReader]:
    # Imported here: the readers use this module's helpers.
    from aria.data import itbench, jira, nezha  # noqa: PLC0415

    return {
        "jira-mongodump": jira.write_subset,
        "itbench-logs": itbench.write_log_windows,
        "nezha-logs": nezha.write_minutes,
    }


def stream_source(source: DataSource, dest: Path, url: str | None = None) -> Path:
    """Run the source's stream reader, then check every file it wrote against its pin."""
    if source.stream is None:
        msg = f"{source.name}: no stream reader configured"
        raise DownloadError(msg)
    reader = _stream_readers()[source.stream.reader]
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        written = reader(source, dest, client, url)
    for path in written:
        _check_pinned(source, path.relative_to(dest).as_posix(), path)
    log.info("dataset.streamed", source=source.name, files=len(written))
    return dest


def hub_repo(url: str) -> str:
    """'https://huggingface.co/datasets/ibm-research/ITBench-Lite' -> 'ibm-research/ITBench-Lite'."""
    parts = [p for p in urlsplit(url).path.split("/") if p]
    if len(parts) != 3 or parts[0] != "datasets":
        msg = f"{url} is not a Hugging Face dataset URL"
        raise DownloadError(msg)
    return "/".join(parts[1:])


def _static_prefix(pattern: str) -> str:
    """The folders of a glob before its first wildcard: 'a/b/*/c' -> 'a/b'."""
    head: list[str] = []
    for part in pattern.split("/")[:-1]:
        if any(ch in part for ch in "*?["):
            break
        head.append(part)
    return "/".join(head)


def hub_files(
    client: httpx.Client, repo: str, commit: str, patterns: list[str]
) -> list[dict[str, Any]]:
    """Every file of the dataset at ``commit`` that a pattern matches, as the Hub lists it."""
    found: dict[str, dict[str, Any]] = {}
    for prefix in sorted({_static_prefix(p) for p in patterns}):
        url: str | None = (
            f"https://huggingface.co/api/datasets/{repo}/tree/{commit}/{quote(prefix)}"
            "?recursive=true&expand=false"
        )
        while url:
            response = _fetch(client, url)
            if response.status_code != httpx.codes.OK:
                msg = f"listing {repo}@{commit[:12]} returned {response.status_code}"
                raise DownloadError(msg)
            for entry in response.json():
                path = str(entry.get("path", ""))
                if entry.get("type") == "file" and any(
                    fnmatch.fnmatchcase(path, p) for p in patterns
                ):
                    found[path] = entry
            url = response.links.get("next", {}).get("url")
    return [found[path] for path in sorted(found)]


def hub_url(repo: str, commit: str, path: str) -> str:
    return f"https://huggingface.co/datasets/{repo}/resolve/{commit}/{quote(path)}"


def blob_id(path: Path) -> str:
    """Git's id for a file's bytes: the sha1 of 'blob <size>', a NUL byte and the bytes."""
    digest = hashlib.sha1(f"blob {path.stat().st_size}\0".encode(), usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hub_verified(path: Path, entry: dict[str, Any]) -> bool:
    """Whether ``path`` holds the bytes the Hub records for ``entry``."""
    if not path.is_file():
        return False
    lfs = entry.get("lfs") or {}
    if lfs.get("oid"):
        return bool(_hash_file(path, "sha256") == lfs["oid"])
    return bool(blob_id(path) == entry.get("oid"))


def download_huggingface(source: DataSource, dest: Path) -> Path:
    """The files ``paths`` match in the dataset repository at the pinned commit."""
    if not (source.url and source.commit and source.paths):
        msg = f"{source.name}: huggingface sources need url, commit and paths"
        raise DownloadError(msg)
    repo = hub_repo(source.url)
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        entries = hub_files(client, repo, source.commit, source.paths)
    if not entries:
        msg = f"{source.name}: no file in {repo}@{source.commit[:12]} matches {source.paths}"
        raise DownloadError(msg)
    for entry in entries:
        target = dest / entry["path"]
        if not target.resolve().is_relative_to(dest.resolve()):
            msg = f"refusing to write {entry['path']} outside {dest}"
            raise DownloadError(msg)
        if hub_verified(target, entry):
            continue
        _stream_to(hub_url(repo, source.commit, entry["path"]), target)
        if not hub_verified(target, entry):
            target.unlink(missing_ok=True)
            msg = f"{source.name}: {entry['path']} does not match the Hub's hash"
            raise DownloadError(msg)
    if source.stream is not None:
        stream_source(source, dest)
    (dest / ".commit").write_text(source.commit + "\n")
    log.info("dataset.fetched", source=source.name, files=len(entries))
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


_ISSUE_FIELDS = (
    "iid",
    "title",
    "description",
    "labels",
    "state",
    "created_at",
    "closed_at",
    "web_url",
)
_MAX_PAGES = 1_000


def download_gitlab(source: DataSource, dest: Path) -> Path:
    """Every issue the query returns, as ``issues.json``, with ``snapshot.json`` recording it."""
    if not source.url:
        msg = f"{source.name}: gitlab sources need the issues API url"
        raise DownloadError(msg)
    record = dest / "snapshot.json"
    if record.exists() and (dest / "issues.json").exists():
        previous = json.loads(record.read_text(encoding="utf-8"))
        if previous.get("url") == source.url and previous.get("params") == source.params:
            log.info("dataset.cached", source=source.name, issues=previous.get("issues"))
            return dest
    issues: list[dict[str, Any]] = []
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for page in range(1, _MAX_PAGES + 1):
            params = {**source.params, "per_page": "100", "page": str(page)}
            response = client.get(source.url, params=params)
            if response.status_code != httpx.codes.OK:
                msg = f"GET {source.url} page {page} returned {response.status_code}"
                raise DownloadError(msg)
            batch = response.json()
            if not batch:
                break
            issues += [{key: item.get(key) for key in _ISSUE_FIELDS} for item in batch]
        else:
            msg = f"{source.name}: more than {_MAX_PAGES} pages; narrow the query"
            raise DownloadError(msg)
    issues.sort(key=lambda issue: int(issue["iid"]))
    body = json.dumps(issues, ensure_ascii=False, sort_keys=True).encode("utf-8")
    (dest / "issues.json").write_bytes(body)
    record.write_text(
        json.dumps(
            {
                "url": source.url,
                "params": source.params,
                "issues": len(issues),
                "sha256": hashlib.sha256(body).hexdigest(),
                "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    log.info("dataset.fetched", source=source.name, issues=len(issues))
    return dest


def _file_name(url: str) -> str:
    """The file a URL names, decoded: ``.../incident%2Blog.zip`` -> ``incident+log.zip``."""
    return unquote(Path(urlsplit(url).path).name)


def download_mirrors(source: DataSource, dest: Path) -> Path:
    """Fetch the first mirror whose bytes match the sha256 pinned beside it, then unpack it."""
    failures: list[str] = []
    for mirror in source.mirrors:
        if mirror.commit is not None:
            copy = source.model_copy(
                update={"url": mirror.url, "commit": mirror.commit, "paths": mirror.paths}
            )
            try:
                download_git(copy, dest)
            except (DownloadError, subprocess.CalledProcessError) as exc:
                failures.append(f"{mirror.url}@{mirror.commit[:12]}: {exc}")
                continue
            log.info("dataset.mirror", source=source.name, url=mirror.url)
            return dest
        target = dest / _file_name(mirror.url)
        try:
            if not (target.exists() and _hash_file(target, "sha256") == mirror.sha256):
                _stream_to(mirror.url, target)
        except (DownloadError, httpx.HTTPError) as exc:
            failures.append(f"{mirror.url}: {exc}")
            continue
        actual = _hash_file(target, "sha256")
        if actual != mirror.sha256:
            target.unlink(missing_ok=True)  # never leave unverified bytes behind
            failures.append(f"{mirror.url}: sha256 mismatch (got {actual})")
            continue
        _extract(target, dest)
        log.info("dataset.mirror", source=source.name, url=mirror.url)
        return dest
    msg = f"{source.name}: no mirror could be used ({'; '.join(failures) or 'none listed'})"
    raise DownloadError(msg)


def _gunzip(archive: Path, target: Path) -> None:
    if target.exists() and target.stat().st_mtime >= archive.stat().st_mtime:
        return  # already unpacked from this download
    partial = target.with_name(target.name + ".part")
    with gzip.open(archive, "rb") as source, partial.open("wb") as out:
        shutil.copyfileobj(source, out, _CHUNK)
    partial.replace(target)


def _extract(archive: Path, dest: Path) -> None:
    if archive.name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(archive) as tarball:
            # The "data" filter refuses absolute paths, "..", devices and links leaving dest.
            tarball.extractall(dest, filter="data")
        return
    if archive.suffix == ".gz":
        _gunzip(archive, dest / archive.stem)
        return
    if archive.suffix != ".zip":
        return
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = (dest / member.filename).resolve()
            if not path.is_relative_to(dest.resolve()):  # zip-slip guard
                msg = f"refusing to extract {member.filename} outside {dest}"
                raise DownloadError(msg)
        bundle.extractall(dest)  # noqa: S202 - a zip, its members validated above
        nested = [m for m in bundle.namelist() if m.endswith(".zip")]
    for inner in nested:
        _extract(dest / inner, dest)


def download(source: DataSource, raw_dir: Path) -> Path:
    dest = raw_dir / source.name
    created = not dest.exists()
    dest.mkdir(parents=True, exist_ok=True)
    try:
        try:
            if source.kind == "git":
                return download_git(source, dest)
            if source.kind == "zenodo":
                return download_zenodo(source, dest)
            if source.kind == "gitlab":
                return download_gitlab(source, dest)
            if source.kind == "huggingface":
                return download_huggingface(source, dest)
            return download_http(source, dest, raw_dir.parent / "checksums.lock")
        except (DownloadError, httpx.HTTPError, subprocess.CalledProcessError) as exc:
            if not source.mirrors:
                raise
            log.warning("dataset.primary_failed", source=source.name, error=str(exc)[:200])
            return download_mirrors(source, dest)
    except Exception:
        if created and not any(dest.iterdir()):
            dest.rmdir()  # leave no empty directory that would look like a downloaded source
        raise
