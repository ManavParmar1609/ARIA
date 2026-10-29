"""The dataset manifest (data/manifest.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_MANIFEST = Path("data/manifest.yaml")


class DataSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    kind: Literal["git", "zenodo", "uci", "http"]
    url: str | None = None
    commit: str | None = None
    paths: list[str] = Field(default_factory=list)
    record: str | None = None
    files: list[str] = Field(default_factory=list)
    dataset_id: int | None = None
    fallback_url: str | None = None
    sha256: str | None = None
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
