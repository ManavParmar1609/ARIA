"""The dataset manifest (data/manifest.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

DEFAULT_MANIFEST = Path("data/manifest.yaml")


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


class DataSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    kind: Literal["git", "zenodo", "uci", "http", "gitlab"]
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
    # Tried in order when the source's own host cannot be reached or serves other bytes.
    mirrors: list[Mirror] = Field(default_factory=list)
    license: str
    citation: str
    description: str


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: dict[str, DataSource]


def load_manifest(path: Path = DEFAULT_MANIFEST) -> Manifest:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest = Manifest.model_validate(raw)
    for name, source in manifest.sources.items():
        source.name = name
    return manifest
