"""Anomalies at four levels in two microservice systems: does ARIA flag the anomalous runs,
leave the normal runs alone, and name the service an anomaly targets?

AnoMod (Ping et al., MSR 2026): 24 anomalies (performance, service, database and code level,
six of each) injected into SocialNetwork and Train Ticket, plus one normal run of each system.
Each run's logs (the newest lines up to ARIA's per-run cap, led by time, level and service) are
triaged offline, end to end, as one run. ARIA never sees the run's name, which is the label.

Measured: anomalous runs flagged (SEV1-3) and paged (SEV1-2), by level; the two normal runs
flagged (too few to estimate a false-alarm rate; they are reported as counts); and, for the
cases whose name targets a service, whether ARIA's first suspect, or one of its first three, is
that service. Baselines on the same runs: a rule that flags any run with an error line, and for
naming the service with the most error lines and a service picked at random. Nothing was tuned
on this data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from aria.config import GuardrailConfig
from aria.data import anomod as data
from aria.data.loghub import parse_generic_line
from aria.evals import ringc
from aria.evals.pipeline import EvalEnvironment

MISSING = {"missing": "download it with: aria data download --source anomod"}
RUN_SYSTEM = {"SN": "social-network", "TT": "train-ticket"}
ERRORS = {"ERROR", "FATAL"}


async def triage(
    env: EvalEnvironment,
    picks: Sequence[int] | None = None,
    root: Path = data.ANOMOD_DIR,
    *,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """One row per run at ``picks`` (positions in :func:`find_cases`)."""
    cases = data.find_cases(root)
    cap = GuardrailConfig().max_lines
    rows: list[dict[str, Any]] = []
    for index in range(len(cases)) if picks is None else picks:
        case = cases[index]
        lines = data.case_lines(case, root, limit=cap)
        if not lines:
            continue
        verdict = await ringc.triage(
            env,
            system=RUN_SYSTEM.get(case.system, "generic"),
            title=f"{data.SYSTEMS.get(case.system, case.system)} logs, run {index}",
            lines=lines,
        )
        errors: Counter[str] = Counter()
        services: set[str] = set()
        for line in lines:
            record = parse_generic_line("generic", line)
            if record.component:
                services.add(record.component)
                if record.level in ERRORS:
                    errors[record.component] += 1
        target = case.target
        rows.append(
            {
                "index": index,
                "system": case.system,
                "case": case.name,
                "level": case.level,
                "anomalous": case.anomalous,
                "target": target,
                "lines": len(lines),
                "services": len(services),
                "error_lines": sum(errors.values()),
                "rank": ringc.rank_of(verdict["candidates"], [target]) if target else None,
                "rank_most_errors": (
                    ringc.rank_of([n for n, _ in errors.most_common()], [target])
                    if target
                    else None
                ),
                **verdict,
            }
        )
        if progress:
            progress(f"{case.system} {case.name}: {verdict['severity']}")
    return rows


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return dict(MISSING)
    anomalous = [r for r in rows if r["anomalous"]]
    normal = [r for r in rows if not r["anomalous"]]
    named = [r for r in anomalous if r["target"]]
    by_level: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in anomalous:
        by_level[row["level"]].append(row)
    random_top = [min(1.0, n / r["services"]) for r in named if r["services"] for n in (1, 3)]
    return {
        "source": "AnoMod (anomalies at four levels in SocialNetwork and Train Ticket)",
        "citation": data.ANOMOD_CITATION,
        "stamp": ringc.STAMP,
        "runs": len(rows),
        "anomalous": len(anomalous),
        "normal": len(normal),
        "by_system": dict(sorted(Counter(r["system"] for r in rows).items())),
        "line_cap": GuardrailConfig().max_lines,
        "aria": {
            "anomalous_flagged": ringc.share(sum(r["flagged"] for r in anomalous), len(anomalous)),
            "anomalous_paged": ringc.share(sum(r["paged"] for r in anomalous), len(anomalous)),
            "normal_flagged": sum(r["flagged"] for r in normal),
            "normal_severity": {r["system"]: r["severity"] for r in normal},
            "naming": ringc.localisation([r["rank"] for r in named]),
        },
        "baselines": {
            "any_error_line": {
                "anomalous_flagged": ringc.share(
                    sum(r["error_lines"] > 0 for r in anomalous), len(anomalous)
                ),
                "normal_flagged": sum(r["error_lines"] > 0 for r in normal),
            },
            "naming_most_errors": ringc.localisation([r["rank_most_errors"] for r in named]),
            "naming_random_expected": {
                "top1": round(sum(random_top[0::2]) / max(1, len(named)), 4),
                "top3": round(sum(random_top[1::2]) / max(1, len(named)), 4),
            },
        },
        "by_level": {
            level: {
                "runs": len(v),
                "flagged": ringc.share(sum(r["flagged"] for r in v), len(v)),
                "severity": ringc.by_level(v),
            }
            for level, v in sorted(by_level.items())
        },
        "cases": [
            {k: r[k] for k in ("system", "case", "level", "severity", "rank", "leading_mode")}
            for r in rows
        ],
    }
