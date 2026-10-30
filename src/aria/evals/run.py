"""Evaluation suites: ``aria eval run --suite smoke|severity|pipeline|robustness|real|all``.

``smoke`` is small and deterministic: CI runs it as a regression gate (``--gate``). ``real``
replays real, expert-labelled logs (``evals/real.py``). ``all`` runs every suite at full size and
regenerates ``docs/evaluation.md``. Results are written as JSON to ``reports/eval/<suite>.json``.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from aria.config import get_app_config
from aria.data.loghub import iter_structured_csv
from aria.data.scenarios import LinePools, Scenario, ScenarioBuilder
from aria.evals import bgl as bg
from aria.evals import edge as ed
from aria.evals import hadoop as hd
from aria.evals import injection as inj
from aria.evals import parsing as ps
from aria.evals import pipeline as pl
from aria.evals import real as rl
from aria.evals import severity as sv
from aria.evals import tickets as tk
from aria.retrieval.seed import MEMORY_SEEDS
from aria.severity.engine import SeverityEngine
from aria.severity.training import SplitSeeds, known_templates

SUITES = ("smoke", "severity", "pipeline", "robustness", "parsing", "edge", "real", "all")
THRESHOLDS = Path("config/eval_thresholds.yaml")
FIXTURES_DIR = Path("tests/fixtures/loghub")  # tiny samples for tests, not for measurement


@dataclass(frozen=True)
class Size:
    severity_seeds: tuple[int, ...]
    severity_per_mode: int
    severity_quiet: int
    tfidf: bool
    pipeline_cases: int
    robustness_cases: int
    memory_per_mode: int


SIZES = {
    "smoke": Size((41,), 1, 1, False, 12, 4, 1),
    "full": Size(SplitSeeds().test, 6, 3, True, 60, 16, 2),
}


def is_fixtures(loghub_dir: Path) -> bool:
    return loghub_dir.resolve() == FIXTURES_DIR.resolve()


def git_sha() -> str | None:
    """The commit measured, marked ``-dirty`` when tracked files had uncommitted changes."""
    try:
        out = subprocess.run(
            ["git", "describe", "--always", "--dirty", "--abbrev=7"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def sample(scenarios: Sequence[Scenario], n: int, *, seed: int = 41) -> list[Scenario]:
    """A deterministic sample that covers every failure mode before repeating one."""
    by_mode: dict[str, list[Scenario]] = {}
    for scenario in scenarios:
        by_mode.setdefault(f"{scenario.system}.{scenario.failure_mode}", []).append(scenario)
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    keys = sorted(by_mode)
    rng.shuffle(keys)
    picked: list[Scenario] = []
    while len(picked) < n and any(by_mode.values()):
        for key in keys:
            if by_mode[key] and len(picked) < n:
                picked.append(by_mode[key].pop(0))
    return picked


async def run(
    suite: str,
    *,
    loghub_dir: Path,
    use_llm: bool = False,
    workers: int = 1,
    limit: int | None = None,
) -> dict[str, Any]:
    if suite not in SUITES:
        msg = f"unknown suite {suite!r}; choose one of {', '.join(SUITES)}"
        raise ValueError(msg)
    size = SIZES["smoke" if suite == "smoke" else "full"]
    builder = ScenarioBuilder(LinePools.from_loghub(loghub_dir))
    config = get_app_config()
    results: dict[str, Any] = {
        "suite": suite,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "llm": use_llm,
        "data": {
            "synthetic": True,
            "description": "semi-synthetic scenarios composed from real Loghub sample lines",
            "test_seeds": list(size.severity_seeds),
            "memory_seeds": list(MEMORY_SEEDS),
            "fixtures": is_fixtures(loghub_dir),
        },
    }
    if suite in ("smoke", "parsing", "all"):
        results["parsing"] = ps.summarize(loghub_dir)
    if suite in ("smoke", "edge", "all"):
        results["edge"] = ed.evaluate(ed.generate())
    if suite in ("edge", "all"):
        results["injection_benchmarks"] = inj.evaluate()
    if suite in ("real", "all"):
        pool = loghub_dir / "HDFS" / "HDFS_2k.log_structured.csv"
        results["real"] = rl.summarize(
            engine=SeverityEngine.load(config.severity),
            known=known_templates(builder, "hdfs"),
            pool_lines={r.message for r in iter_structured_csv("hdfs", pool)}
            if pool.exists()
            else None,
        )
        bgl_pool = loghub_dir / "BGL" / "BGL_2k.log_structured.csv"
        results["real"]["bgl"] = bg.summarize(
            engine=SeverityEngine.load(config.severity),
            known=known_templates(builder, "bgl"),
            pool={r.message for r in iter_structured_csv("bgl", bgl_pool)}
            if bgl_pool.exists()
            else set(),
            workers=workers,
        )
        results["real"]["uci_tickets"] = tk.summarize(Path(config.severity.ticket_model_file))
        results["real"]["hadoop"] = await _hadoop(builder, loghub_dir, size, workers)
    test = sv.held_out(
        builder,
        seeds=size.severity_seeds,
        per_mode=size.severity_per_mode,
        quiet_per_system=size.severity_quiet,
    )
    if suite in ("smoke", "severity", "all"):
        engine = SeverityEngine.load(config.severity)
        features = sv.featurize(builder, test, workers=workers)
        cases = sv.score(engine, test, features)
        tfidf = None
        if size.tfidf:
            tfidf = sv.tfidf_baseline(
                builder, test, per_mode=size.severity_per_mode, quiet_per_system=size.severity_quiet
            )
        results["severity"] = sv.summarize(
            cases, alpha=engine.alpha, majority=sv.majority_label(), tfidf=tfidf
        )
        results["severity"]["model_version"] = engine.model.version if engine.model else None
    if suite in ("smoke", "pipeline", "robustness", "all"):
        benign_modes = {k for k, mode in builder.pools.modes.items() if mode.benign}
        with tempfile.TemporaryDirectory(prefix="aria-eval-") as tmp:
            env = await pl.EvalEnvironment.create(
                builder,
                db_path=Path(tmp) / "eval.db",
                use_llm=use_llm,
                memory_per_mode=size.memory_per_mode,
                workers=workers,
            )
            try:
                results["memory_incidents"] = env.memory_size
                if suite in ("smoke", "pipeline", "all"):
                    picked = sample(test, limit or size.pipeline_cases)
                    runs = [
                        await pl.run_case(
                            env,
                            scenario,
                            use_llm=use_llm,
                            benign=f"{scenario.system}.{scenario.failure_mode}" in benign_modes,
                        )
                        for scenario in picked
                    ]
                    results["pipeline"] = pl.summarize(
                        runs,
                        budget_tokens=config.budgets.max_tokens,
                        relevant_per_mode=len(MEMORY_SEEDS) * size.memory_per_mode,
                    )
                    results["pipeline"]["providers"] = pl.provider_stats(runs)
                    results["pipeline_cases"] = [asdict(r) for r in runs]
                if suite in ("smoke", "robustness", "all"):
                    attackable = [s for s in test if s.failure_mode != "none"]
                    picked = sample(attackable, limit or size.robustness_cases, seed=7)
                    robust = [await pl.robustness_case(env, scenario) for scenario in picked]
                    results["robustness"] = pl.summarize_robustness(robust)
                    results["robustness_cases"] = robust
            finally:
                await env.aclose()
    return results


async def _hadoop(
    builder: ScenarioBuilder, loghub_dir: Path, size: Size, workers: int
) -> dict[str, Any]:
    """The Hadoop jobs, each triaged end to end in a fresh offline environment."""
    if hd.find_labels() is None:
        return {"missing": "download it with: aria data download --source loghub-hadoop"}
    sample = loghub_dir / "Hadoop" / "Hadoop_2k.log_structured.csv"
    with tempfile.TemporaryDirectory(prefix="aria-eval-real-") as tmp:
        env = await pl.EvalEnvironment.create(
            builder,
            db_path=Path(tmp) / "real.db",
            memory_per_mode=size.memory_per_mode,
            workers=workers,
        )
        try:
            return await hd.evaluate(
                env,
                known=known_templates(builder, "hadoop"),
                pool={r.message for r in iter_structured_csv("hadoop", sample)}
                if sample.exists()
                else None,
            )
        finally:
            await env.aclose()


def save(results: dict[str, Any], out_dir: Path = Path("reports/eval")) -> Path:
    """Write the results as ``<out_dir>/<suite>[-llm].json`` and return the path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{results['suite']}{'-llm' if results['llm'] else ''}.json"
    path.write_text(json.dumps(results, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def _lookup(results: dict[str, Any], dotted: str) -> Any:
    node: Any = results
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def check_gate(results: dict[str, Any], suite: str, path: Path = THRESHOLDS) -> list[str]:
    """Failures of the suite's thresholds (empty when the gate passes)."""
    spec = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get(suite, {})
    failures = []
    if results.get("data", {}).get("fixtures"):
        failures.append(
            "the thresholds are set on the Loghub 2k samples, but this ran on the test fixtures; "
            "download the samples first (make data)"
        )
    for dotted, bound in spec.items():
        value = _lookup(results, dotted)
        if not isinstance(value, int | float):
            failures.append(f"{dotted}: missing from the results")
            continue
        if "min" in bound and value < bound["min"]:
            failures.append(f"{dotted} = {value} is below {bound['min']}")
        if "max" in bound and value > bound["max"]:
            failures.append(f"{dotted} = {value} is above {bound['max']}")
    return failures


def default_workers() -> int:
    return max(1, min(4, (os.cpu_count() or 2) - 1))
