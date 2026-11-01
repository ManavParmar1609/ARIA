"""The dataset manifest (data/manifest.yaml)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_MANIFEST = Path("data/manifest.yaml")
_HEX = re.compile(r"[0-9a-f]+")


class Mirror(BaseModel):
    """A copy of a source on another host: one file trusted through its sha256, or a git
    repository at a pinned commit (content-addressed) from which ``paths`` are checked out."""

    model_config = ConfigDict(extra="forbid")

    url: str
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    paths: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_integrity_check(self) -> Mirror:
        if (self.sha256 is None) == (self.commit is None):
            msg = "a mirror needs exactly one of sha256 (a file) or commit (a git repository)"
            raise ValueError(msg)
        if self.commit is not None and not self.paths:
            msg = "a git mirror needs the paths to check out"
            raise ValueError(msg)
        return self


class Stream(BaseModel):
    """Part of a file too large to keep, read as it arrives and never stored whole.

    ``reader`` names the code that reads it (see ``aria.data.download.stream_source``);
    ``member`` is the file inside a zip to read, for a zipped source; ``keep`` and ``limit`` say
    what the reader keeps; ``minutes`` is how much of a log it keeps before the moment the log is
    read for.
    """

    model_config = ConfigDict(extra="forbid")

    reader: Literal["itbench-logs"]
    member: str | None = None
    keep: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, gt=0)
    minutes: int | None = Field(default=None, gt=0)


class DataSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    kind: Literal["git", "zenodo", "uci", "http", "gitlab", "huggingface"]
    url: str | None = None
    commit: str | None = None
    paths: list[str] = Field(default_factory=list)
    # Checked-out files to store gzipped (globs), for a git source of plain-text logs too big
    # to keep as text.
    compress: list[str] = Field(default_factory=list)
    record: str | None = None
    files: list[str] = Field(default_factory=list)
    # Unpack downloaded archives. Off for an archive too large to keep unpacked beside itself:
    # the evaluation reads it from inside the zip.
    extract: bool = True
    dataset_id: int | None = None
    fallback_url: str | None = None
    # Query parameters for an API source (kind "gitlab"): fixed, so the set of records is.
    params: dict[str, str] = Field(default_factory=dict)
    sha256: str | None = None
    # Pinned checksums by file name, "md5:<hex>" or "sha256:<hex>": a Zenodo file must match
    # both its pin and the checksum the record publishes, so a record that changes its files
    # is refused; for a streamed source they pin the files the reader writes.
    checksums: dict[str, str] = Field(default_factory=dict)
    # Read part of a large file as it streams in, instead of downloading it (see Stream).
    stream: Stream | None = None
    # Tried in order when the source's own host cannot be reached or serves other bytes.
    mirrors: list[Mirror] = Field(default_factory=list)
    license: str
    citation: str
    description: str

    @model_validator(mode="after")
    def _checksums_name_an_algorithm(self) -> DataSource:
        for name, pinned in self.checksums.items():
            algorithm, _, digest = pinned.partition(":")
            width = {"md5": 32, "sha256": 64}.get(algorithm)
            if width is None or len(digest) != width or not _HEX.fullmatch(digest):
                msg = f"checksum for {name} must be md5:<32 hex> or sha256:<64 hex>"
                raise ValueError(msg)
        return self


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: dict[str, DataSource]


def load_manifest(path: Path = DEFAULT_MANIFEST) -> Manifest:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest = Manifest.model_validate(raw)
    for name, source in manifest.sources.items():
        source.name = name
    return manifest
