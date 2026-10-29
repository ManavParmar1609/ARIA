"""Seed incident memory with a labelled, semi-synthetic history.

Each scenario (real Loghub lines, synthetic composition) is parsed by the production parser and
summarised deterministically; its resolution comes from the failure mode's runbook. Rows are
marked ``synthetic=True`` and ``source="curated"`` and say so wherever they are shown. MTTR is
left empty: the scenarios do not record how long a fix took, and ARIA does not invent it.

Seeds 51-52 are used, disjoint from the severity model's train (11-14), calibration (21, 31-32)
and test (41-42) seeds, so evaluation never retrieves its own test windows.
"""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path

from aria.config import GuardrailConfig
from aria.data.scenarios import Scenario, ScenarioBuilder
from aria.evidence import EvidenceStore
from aria.parsing.parser import parse_lines
from aria.retrieval.memory import MemoryIncident
from aria.retrieval.runbooks import Runbook, load_runbooks

MEMORY_SEEDS = (51, 52)
SEED_SALT = b"aria-memory-v1"


def incident_from_scenario(scenario: Scenario, runbooks: dict[str, Runbook]) -> MemoryIncident:
    batch = parse_lines(
        scenario.lines,
        system=scenario.system,
        guard=GuardrailConfig(),
        evidence=EvidenceStore(),
        salt=SEED_SALT,
    ).batch
    features = batch.features
    errors = [t for t in batch.templates if t.error_like][:3] or batch.templates[:2]
    signature = " | ".join(t.template for t in errors)
    minutes = features.duration_s / 60
    summary = (
        f"{features.error_events} error events on {features.error_nodes} of {features.distinct_nodes} "
        f"nodes over {minutes:.0f} min (peak {features.peak_errors_per_min:.0f}/min)."
    )
    runbook = runbooks.get(scenario.runbook or "")
    if runbook is not None:
        steps = "; ".join(s.text.rstrip(".") for s in runbook.mitigate[:2])
        resolution = f"Followed runbook {runbook.slug}: {steps}."
    elif scenario.failure_mode == "none":
        resolution = "No action needed: routine traffic."
    else:
        resolution = "No action needed: known benign noise."
    return MemoryIncident(
        id=f"syn-{scenario.id.removeprefix('scn-')}",
        title=scenario.title,
        system=scenario.system,
        failure_mode=scenario.failure_mode,
        severity=scenario.severity,
        summary=summary,
        resolution=resolution,
        signature=signature[:2_000],
        components=(features.critical_components or features.components)[:6],
        runbook_slug=runbook.slug if runbook else None,
        first_seen=scenario.start,
        last_seen=scenario.end,
        occurrences=1,
        affected_nodes=len(scenario.nodes),
        mttr_minutes=None,
        source="curated",
        synthetic=True,
    )


def _from_scenario(scenario: Scenario, runbooks_dir: str) -> MemoryIncident:
    return incident_from_scenario(scenario, load_runbooks(Path(runbooks_dir)))


def seed_incidents(
    builder: ScenarioBuilder,
    runbooks_dir: Path,
    *,
    seeds: Iterable[int] = MEMORY_SEEDS,
    per_mode: int = 3,
    quiet_per_system: int = 1,
    workers: int = 1,
) -> list[MemoryIncident]:
    scenarios = [
        scenario
        for seed in seeds
        for scenario in builder.suite(
            seed=seed, per_mode=per_mode, quiet_per_system=quiet_per_system
        )
        if scenario.failure_mode != "none"  # quiet windows are not incidents
    ]
    if workers > 1 and len(scenarios) > 2 * workers:
        with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
            return list(
                pool.map(
                    _from_scenario, scenarios, [str(runbooks_dir)] * len(scenarios), chunksize=4
                )
            )
    runbooks = load_runbooks(runbooks_dir)
    return [incident_from_scenario(s, runbooks) for s in scenarios]
