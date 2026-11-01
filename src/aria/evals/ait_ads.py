"""Security alerts from attacked networks: does ARIA rate the windows of an attack above the
routine alert noise, and does it page on the steps that mean a compromise?

The AIT Alert Data Set (Landauer et al., CSET 2024): eight simulated company networks, each
attacked once in several steps, watched by three intrusion detection systems (Wazuh, Suricata
and AMiner). Most of its 2.6 million alerts are false positives from ordinary users, as in a
real security operations centre. Each scenario's alerts are cut into contiguous 20-minute
windows (the length the BGL section uses); a window counts as an attack window when an attack
step's time range overlaps it, and as routine otherwise. ARIA rates each window from its alert
lines alone, through the production parser (and its default line cap), the severity engine and
the offline policy. Like a deployment, it remembers the routine templates of every earlier
window of the same network (what its review step teaches it), so a template counts as new
only against that history. The attack steps never reach ARIA.

Measured: how well ARIA's probability of SEV1-2, and its level, rank attack windows above
routine ones (AUROC, overall and per network); how often it flags (SEV1-3) and pages (SEV1-2)
each; and, per occurrence of the steps that mean a compromise or harm (a web shell, password
cracking, a reverse shell, privilege escalation, a stopped service, data theft over DNS), whether
any window overlapping it was paged. A step missed is a severe miss; its rate carries an exact
one-sided upper bound. Baselines on the same windows: the detectors' own highest Wazuh rule level
(a page at level 12 or above, "high importance" in Wazuh's rule classification; a flag at 7 or
above), the number of alerts, ARIA's rules alone, its model alone and the keyword rule. Nothing
was tuned on this data.
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from multiprocessing import get_context
from pathlib import Path
from statistics import median
from typing import Any

from aria.config import GuardrailConfig, get_app_config
from aria.data import ait_ads as data
from aria.evals import ringc
from aria.evidence import EvidenceStore
from aria.parsing.parser import parse_lines
from aria.parsing.signals import error_count, warning_count
from aria.severity.engine import SeverityEngine

SYSTEM = "ait-ads"  # no format ARIA knows: every line goes through the generic parser
WINDOW_MIN = 20
# Steps that mean a compromise or harm, rather than reconnaissance.
HARMFUL = (
    "webshell",
    "cracking",
    "reverse_shell",
    "privilege_escalation",
    "service_stop",
    "dnsteal",
)
IDS_PAGE_LEVEL = 12  # Wazuh: 12-15 are high-importance events and attacks
IDS_FLAG_LEVEL = 7
HISTORY = 20_000  # templates a run reads back from the store, as the graph does
SALT = b"aria-eval-ait-ads"
MISSING = {"missing": "download it with: aria data download --source ait-ads"}


def _ids_level(level: int) -> str:
    if level >= IDS_PAGE_LEVEL:
        return "SEV2"
    return "SEV3" if level >= IDS_FLAG_LEVEL else "SEV4"


def score_scenario(
    scenario: str,
    root: Path = data.AIT_DIR,
    *,
    engine: SeverityEngine | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """One row per window of one scenario, in time order, each judged with the routine
    templates of the scenario's earlier windows as history."""
    engine = engine or SeverityEngine.load(get_app_config().severity)
    guard = GuardrailConfig()
    phases = data.read_phases(root).get(scenario, [])
    history: dict[str, None] = {}
    rows: list[dict[str, Any]] = []
    stream = data.windows(data.iter_alerts(scenario, root), phases, scenario, WINDOW_MIN)
    for window in stream:
        if limit is not None and len(rows) >= limit:
            break
        lines = [a.line for a in window.alerts]
        parsed = parse_lines(
            lines,
            system=SYSTEM,
            guard=guard,
            evidence=EvidenceStore(),
            known_templates=list(history)[-HISTORY:],
            salt=SALT,
        ).batch
        verdict = ringc.judge(engine, parsed.features, system=SYSTEM)
        for template in parsed.templates:
            if not error_count(template) and not warning_count(template):
                history.pop(template.template, None)
                history[template.template] = None
        levels = [a.level for a in window.alerts if a.level is not None]
        rows.append(
            {
                "scenario": scenario,
                "start": datetime.fromtimestamp(window.start, tz=UTC).isoformat(),
                "alerts": len(lines),
                "read": min(len(lines), guard.max_lines),
                "sources": dict(Counter(a.source for a in window.alerts)),
                "max_level": max(levels, default=0),
                "phases": list(window.phases),
                "attack": bool(window.phases),
                "harmful": any(p in HARMFUL for p in window.phases),
                **verdict,
            }
        )
    return rows


def _scenario_rows(args: tuple[str, str, int | None]) -> list[dict[str, Any]]:
    scenario, root, limit = args
    return score_scenario(scenario, Path(root), limit=limit)


def _flag_rates(rows: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    attack = [r for r in rows if r["attack"]]
    routine = [r for r in rows if not r["attack"]]
    return {
        "attack_flagged": ringc.share(sum(r[key] in ringc.FLAGGED for r in attack), len(attack)),
        "attack_paged": ringc.share(sum(r[key] in ringc.SEVERE for r in attack), len(attack)),
        "routine_flagged": ringc.share(sum(r[key] in ringc.FLAGGED for r in routine), len(routine)),
        "routine_paged": ringc.share(sum(r[key] in ringc.SEVERE for r in routine), len(routine)),
    }


def _steps(
    rows: Sequence[dict[str, Any]], phases: dict[str, list[data.Phase]], key: str
) -> dict[str, Any]:
    """Per attack step: occurrences, how many produced any alert, and how many were paged."""
    by_step: dict[str, Counter[str]] = defaultdict(Counter)
    for scenario, steps in phases.items():
        windows = [r for r in rows if r["scenario"] == scenario]
        for step in steps:
            seen = [r for r in windows if step.name in r["phases"]]
            tally = by_step[step.name]
            tally["occurrences"] += 1
            tally["with_alerts"] += bool(seen)
            tally["flagged"] += any(r[key] in ringc.FLAGGED for r in seen)
            tally["paged"] += any(r[key] in ringc.SEVERE for r in seen)
    harmful = [by_step[s] for s in HARMFUL if s in by_step]
    occurrences = sum(t["occurrences"] for t in harmful)
    paged = sum(t["paged"] for t in harmful)
    return {
        "by_step": {k: dict(v) for k, v in sorted(by_step.items())},
        "harmful_occurrences": occurrences,
        "harmful_without_alerts": sum(t["occurrences"] - t["with_alerts"] for t in harmful),
        "severe_miss": ringc.miss_rate(occurrences - paged, occurrences),
        "harmful_flagged": ringc.share(sum(t["flagged"] for t in harmful), occurrences),
    }


def summarize(
    rows: Sequence[dict[str, Any]], phases: dict[str, list[data.Phase]]
) -> dict[str, Any]:
    if not rows:
        return dict(MISSING)
    truth = [bool(r["attack"]) for r in rows]
    for row in rows:
        row.setdefault("ids", _ids_level(int(row["max_level"])))
    scenarios = sorted({r["scenario"] for r in rows})
    per_scenario = {}
    for scenario in scenarios:
        subset = [r for r in rows if r["scenario"] == scenario]
        per_scenario[scenario] = {
            "windows": len(subset),
            "attack_windows": sum(r["attack"] for r in subset),
            "auroc": ringc.ranking(
                [r["attack"] for r in subset], [r["severe_probability"] for r in subset]
            )["auroc"],
        }
    aurocs = [v["auroc"] for v in per_scenario.values() if v["attack_windows"]]
    methods = {"aria": "severity", "rules_only": "rules", "model_only": "model"}
    methods |= {"keyword": "keyword", "ids_level": "ids"}
    return {
        "source": "the AIT Alert Data Set (AIT-ADS)",
        "citation": data.AIT_CITATION,
        "stamp": ringc.STAMP,
        "window_min": WINDOW_MIN,
        "scenarios": len(scenarios),
        "windows": len(rows),
        "attack_windows": sum(truth),
        "routine_windows": len(rows) - sum(truth),
        "alerts": sum(r["alerts"] for r in rows),
        "line_cap": GuardrailConfig().max_lines,
        "windows_over_line_cap": sum(1 for r in rows if r["alerts"] > r["read"]),
        "ranking": {
            "aria_probability": ringc.ranking(truth, [r["severe_probability"] for r in rows]),
            "aria_level": ringc.ranking(truth, [ringc.ORDINAL[r["severity"]] for r in rows]),
            "ids_level": ringc.ranking(truth, [float(r["max_level"]) for r in rows]),
            "alert_count": ringc.ranking(truth, [float(r["alerts"]) for r in rows]),
            "keyword": ringc.ranking(truth, [ringc.ORDINAL[r["keyword"]] for r in rows]),
            "rules_only": ringc.ranking(truth, [ringc.ORDINAL[r["rules"]] for r in rows]),
        },
        "per_scenario": per_scenario,
        "per_scenario_auroc": {
            "median": round(median(aurocs), 4) if aurocs else None,
            "worst": round(min(aurocs), 4) if aurocs else None,
            "below_0_5": sum(1 for a in aurocs if a < 0.5),
        },
        "rates": {name: _flag_rates(rows, key) for name, key in methods.items()},
        "steps": {name: _steps(rows, phases, key) for name, key in methods.items()},
        "severity": {
            "attack": ringc.by_level([r for r in rows if r["attack"]]),
            "routine": ringc.by_level([r for r in rows if not r["attack"]]),
        },
        "review": {
            "attack": ringc.share(sum(r["needs_review"] for r in rows if r["attack"]), sum(truth)),
            "routine": ringc.share(
                sum(r["needs_review"] for r in rows if not r["attack"]), len(rows) - sum(truth)
            ),
        },
        "rules_on_paged_routine_windows": Counter(
            rule
            for r in rows
            if not r["attack"] and r["severity"] in ringc.SEVERE
            for rule in r["fired"]
        ).most_common(5),
    }


async def evaluate(
    root: Path = data.AIT_DIR,
    *,
    workers: int = 1,
    limit: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(summary, rows): every scenario's windows (the first ``limit`` of each), scored."""
    scenarios = data.scenarios(root)
    if not scenarios:
        return dict(MISSING), []
    jobs = [(s, str(root), limit) for s in scenarios]
    if workers > 1:
        loop = asyncio.get_running_loop()
        with ProcessPoolExecutor(
            max_workers=min(workers, len(jobs)), mp_context=get_context("spawn")
        ) as pool:
            shares = await asyncio.gather(
                *(loop.run_in_executor(pool, _scenario_rows, job) for job in jobs)
            )
    else:
        shares = [await asyncio.to_thread(_scenario_rows, job) for job in jobs]
    rows = [row for share in shares for row in share]
    if progress:
        progress(f"{len(rows):,} windows from {len(scenarios)} networks")
    return summarize(rows, data.read_phases(root)), rows
