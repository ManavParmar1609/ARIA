"""Ring C suites, one per new domain: ``aria eval run --suite <name>`` runs one alone, and
``--suite all`` runs every one whose data is downloaded (the others report how to fetch it).

Each suite's summary goes under ``results["domains"][<name>]`` and its rows, one per window,
case or ticket, under ``results["domain_cases"][<name>]`` (kept out of the published
``docs/eval-results.json``). The pipeline suites share their cases out over worker processes,
each with an offline environment of its own, as the OpenStack suite does.
"""

from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from aria.config import get_settings
from aria.data import rcaeval as rcaeval_data
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.evals import ait_ads, rcaeval
from aria.evals.pipeline import EvalEnvironment

SUITES = ("ait-ads", "rcaeval")
# The manifest source each suite reads.
SOURCES = {
    "ait-ads": "ait-ads",
    "rcaeval": "rcaeval-re3",
}
# Suites that triage cases end to end, with what lists their cases and what triages a share.
Triage = Callable[[EvalEnvironment, Sequence[int], Path], Awaitable[list[dict[str, Any]]]]
_PIPELINE: dict[str, tuple[Callable[[Path], int], Triage, Callable[..., dict[str, Any]], Path]] = {
    "rcaeval": (
        lambda root: len(rcaeval_data.find_cases(root)),
        rcaeval.triage,
        rcaeval.summarize,
        rcaeval_data.RCAEVAL_DIR,
    ),
}
_MISSING = {
    "ait-ads": ait_ads.MISSING,
    "rcaeval": rcaeval.MISSING,
}


async def _pipeline_rows(
    name: str, loghub_dir: Path, picks: Sequence[int], memory_per_mode: int, root: Path
) -> list[dict[str, Any]]:
    builder = ScenarioBuilder(LinePools.from_loghub(loghub_dir))
    with tempfile.TemporaryDirectory(prefix=f"aria-eval-{name}-") as tmp:
        env = await EvalEnvironment.create(
            builder, db_path=Path(tmp) / f"{name}.db", memory_per_mode=memory_per_mode
        )
        try:
            return await _PIPELINE[name][1](env, picks, root)
        finally:
            await env.aclose()


def _share(
    name: str, loghub_dir: str, picks: list[int], memory_per_mode: int, root: str
) -> list[dict[str, Any]]:
    """One process's share of a pipeline suite's cases."""
    return asyncio.run(_pipeline_rows(name, Path(loghub_dir), picks, memory_per_mode, Path(root)))


async def pipeline_suite(
    name: str,
    *,
    loghub_dir: Path,
    workers: int = 1,
    memory_per_mode: int = 2,
    limit: int | None = None,
    root: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    count_cases, _, summarize, default_root = _PIPELINE[name]
    root = root or default_root
    count = count_cases(root)
    if not count:
        return dict(_MISSING[name]), []
    picks = list(range(count))[:limit]
    if workers > 1 and len(picks) > workers:
        loop = asyncio.get_running_loop()
        with ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn")) as pool:
            shares = await asyncio.gather(
                *(
                    loop.run_in_executor(
                        pool,
                        _share,
                        name,
                        str(loghub_dir),
                        picks[i::workers],
                        memory_per_mode,
                        str(root),
                    )
                    for i in range(workers)
                )
            )
        rows = [row for share in shares for row in share]
    else:
        rows = await _pipeline_rows(name, loghub_dir, picks, memory_per_mode, root)
    rows.sort(key=lambda r: (r.get("index", 0), r.get("window", "")))
    summary = summarize(rows)
    if "missing" not in summary:
        summary["found"] = count  # cases present; a case with nothing to read is left out
    return summary, rows


def data_dir(name: str) -> Path:
    """Where ``aria data download`` puts the suite's source (it honours ARIA_DATA_DIR)."""
    return get_settings().data_dir / "raw" / SOURCES[name]


async def run_suite(
    name: str,
    *,
    loghub_dir: Path,
    workers: int = 1,
    memory_per_mode: int = 2,
    limit: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(summary, rows) of one ring C suite."""
    root = data_dir(name)
    if name == "ait-ads":
        return await ait_ads.evaluate(root, workers=workers, limit=limit)
    return await pipeline_suite(
        name,
        loghub_dir=loghub_dir,
        workers=workers,
        memory_per_mode=memory_per_mode,
        limit=limit,
        root=root,
    )


async def add_to(
    results: dict[str, Any],
    suite: str,
    *,
    loghub_dir: Path,
    workers: int = 1,
    memory_per_mode: int = 2,
    limit: int | None = None,
) -> None:
    """Run ``suite`` (or, for ``all``, every ring C suite) into ``results``."""
    names = SUITES if suite == "all" else (suite,)
    summaries = results.setdefault("domains", {})
    rows = results.setdefault("domain_cases", {})
    for name in names:
        summaries[name], rows[name] = await run_suite(
            name,
            loghub_dir=loghub_dir,
            workers=workers,
            memory_per_mode=memory_per_mode,
            limit=limit,
        )
