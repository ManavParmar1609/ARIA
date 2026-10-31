"""Choose the console samples' sizes by how a run rates them.

A sample offers "How many servers?" or "How fast?" only where the answer changes the severity a
visitor sees. That severity comes from the parser and this engine, not from the sample's label,
so each candidate size is rated here the way a run without a model rates it: the same parser and
guardrails, the routine-template history ``aria seed`` stores, and the engine's decision.

Rating every size of every sample takes seconds on a laptop and minutes on a small shared CPU, so
``aria seed`` does it once and saves the result next to the models. The API loads it while the
inputs it was rated from are unchanged, and otherwise falls back to the samples' labels.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from aria import __version__
from aria.config import AppConfig, GuardrailConfig, Settings
from aria.contracts.base import Severity
from aria.data.scenarios import (
    CATALOG_PATH,
    RATE_STEPS,
    SAMPLE_BACKGROUND_PER_MIN,
    SAMPLE_MINUTES,
    SAMPLE_RATE,
    SAMPLE_SEED,
    SAMPLE_SERVERS,
    SERVER_STEPS,
    SampleSizes,
    Scenario,
    ScenarioBuilder,
    SizeChoice,
)
from aria.evidence import EvidenceStore
from aria.observability.logging import get_logger
from aria.parsing.parser import parse_lines
from aria.severity.engine import SeverityEngine
from aria.severity.model import live_model_path
from aria.severity.policy import decide
from aria.severity.training import TRAIN_SALT, known_templates

log = get_logger(__name__)

SIZES_FILE = "sample_sizes.json"


class RunRating:
    """The severity a run without a model gives a sample.

    Samples stay under the line count at which a run splits its parsing, so one shard parses
    them as a run does.
    """

    def __init__(
        self, builder: ScenarioBuilder, engine: SeverityEngine, guard: GuardrailConfig
    ) -> None:
        self._builder = builder
        self._engine = engine
        self._guard = guard

    def __call__(self, scenario: Scenario) -> Severity:
        batch = parse_lines(
            scenario.lines,
            system=scenario.system,
            guard=self._guard,
            evidence=EvidenceStore(),
            known_templates=known_templates(self._builder, scenario.system),
            salt=TRAIN_SALT,
        ).batch
        pre = self._engine.preliminary(batch.features, evidence=EvidenceStore())
        return decide(
            pre, gate=self._engine.gate, llm_unavailable_reason="sizing a sample"
        ).severity


def fingerprint(settings: Settings, config: AppConfig, lines: Path) -> str:
    """What the ratings depend on: the lines, the catalog, the rules, the model in use, the
    guardrails and the sample sizes tried. Saved sizes from other inputs are not used."""
    digest = hashlib.sha256()
    trained = Path(config.severity.log_model_file)
    live = live_model_path(trained, settings.models_dir)
    for path in (
        CATALOG_PATH,
        Path(config.severity.rules_file),
        live if live.is_file() else trained,
    ):
        digest.update(path.read_bytes() if path.is_file() else b"-")
    digest.update(str(lines.resolve()).encode())
    for csv in sorted(lines.glob("*/*_2k.log_structured.csv")):
        digest.update(f"{csv.parent.name}:{csv.stat().st_size}".encode())
    digest.update(config.guardrails.model_dump_json().encode())
    constants = [
        SERVER_STEPS,
        RATE_STEPS,
        SAMPLE_SEED,
        SAMPLE_MINUTES,
        SAMPLE_BACKGROUND_PER_MIN,
        SAMPLE_SERVERS,
        SAMPLE_RATE,
        __version__,
    ]
    digest.update(json.dumps(constants).encode())
    return digest.hexdigest()[:16]


def rate_samples(builder: ScenarioBuilder, rating: RunRating) -> dict[str, SampleSizes]:
    """Every sample's sizes, chosen by ``rating``."""
    builder.rate_with(rating)
    return {
        key: builder.sample_sizes(key)
        for key in builder.pools.available_modes()
        if builder.pools.modes[key].card is not None
    }


def _choice(values: Any) -> SizeChoice | None:
    if values is None:
        return None
    if (
        not isinstance(values, list)
        or len(values) < 2
        or not all(isinstance(v, int) and v > 0 for v in values)
    ):
        msg = f"not a size choice: {values!r}"
        raise ValueError(msg)
    return SizeChoice(tuple(values))


def save_sizes(path: Path, sizes: Mapping[str, SampleSizes], key: str) -> None:
    data = {
        "fingerprint": key,
        "sizes": {
            mode: {
                "servers": list(s.servers.values) if s.servers else None,
                "rate": list(s.rate.values) if s.rate else None,
            }
            for mode, s in sorted(sizes.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written whole, then renamed: a server reading it while it is written sees the old file.
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def load_sizes(path: Path, key: str) -> dict[str, SampleSizes] | None:
    """The saved sizes, or None when there are none, they are unreadable or their inputs changed."""
    try:
        data = json.loads(path.read_text())
        if data.get("fingerprint") != key:
            return None
        return {
            mode: SampleSizes(_choice(entry.get("servers")), _choice(entry.get("rate")))
            for mode, entry in data["sizes"].items()
        }
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
        log.warning("samples.sizes_unreadable", path=str(path), error=str(exc))
        return None


def rate_and_save(
    builder: ScenarioBuilder, settings: Settings, config: AppConfig, lines: Path
) -> tuple[Path, int]:
    """Rate every sample's sizes and save them; returns the file and how many samples offer one."""
    engine = SeverityEngine.load(config.severity, models_dir=settings.models_dir)
    sizes = rate_samples(builder, RunRating(builder, engine, config.guardrails))
    path = settings.models_dir / SIZES_FILE
    save_sizes(path, sizes, fingerprint(settings, config, lines))
    return path, sum(1 for s in sizes.values() if s.servers or s.rate)


def saved_sizes(
    settings: Settings, config: AppConfig, lines: Path
) -> dict[str, SampleSizes] | None:
    """Sizes ``aria seed`` rated from these same inputs, if it has."""
    return load_sizes(settings.models_dir / SIZES_FILE, fingerprint(settings, config, lines))
