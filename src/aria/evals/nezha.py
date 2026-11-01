"""Faults injected into Online Boutique's pods: does ARIA flag the logs after each fault, leave
the logs before it alone, and name the service the fault went into?

Nezha's Online Boutique data (Yu et al., ESEC/FSE 2023): two days of faults injected one at a
time into the shop's pods (CPU contention and consumption, network delay, a thrown exception, a
wrong return value), about eight minutes apart, every service logging throughout. Each fault
gives two windows, the service logs of the minute before it and of the minute from it on, each
triaged offline, end to end, as one run with the default per-run line cap (the shop logs more
lines a minute than the cap, so ARIA reads the start of each window). Where the fault list's
two times for a fault disagree, the healthy window ends at the earlier and the faulty one
starts at the later. ARIA never sees the fault list. Measured as for RCAEval
(``aria.evals.rcaeval``): windows flagged, each fault's window against the one before it, and
whether ARIA names the service at fault, beside the same baselines. Nothing was tuned on this
data.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from aria.config import GuardrailConfig
from aria.data import nezha as data
from aria.evals import rcaeval, ringc
from aria.evals.pipeline import EvalEnvironment

MISSING = {"missing": "download it with: aria data download --source nezha"}
WINDOW_MIN = 1  # minutes either side of a fault; the download keeps the manifest's minutes
RUN_SYSTEM = "online-boutique"


async def triage(
    env: EvalEnvironment,
    picks: Sequence[int] | None = None,
    root: Path = data.NEZHA_DIR,
    *,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Two rows per fault at ``picks`` (positions in :func:`find_faults`): before, then after."""
    faults = data.find_faults(root)
    cap = GuardrailConfig().max_lines
    rows: list[dict[str, Any]] = []
    for index in range(len(faults)) if picks is None else picks:
        fault = faults[index]
        split = data.windows(fault, root, WINDOW_MIN)
        for window, lines, services in (
            ("healthy", split.before, split.services_before),
            ("faulty", split.after, split.services_after),
        ):
            if not lines:
                continue
            verdict = await ringc.triage(
                env, system=RUN_SYSTEM, title=f"Online Boutique logs, fault {index}", lines=lines
            )
            errors = rcaeval.error_counts(lines[:cap])
            rows.append(
                {
                    "index": index,
                    "case": fault.id,
                    "system": "OB",
                    "day": fault.day,
                    "service": fault.service,
                    "fault": fault.kind,
                    # seconds between the fault list's two times for the fault
                    "times_apart_s": abs(fault.at - (fault.noted_at or fault.at)),
                    "window": window,
                    "faulty": window == "faulty",
                    "lines": len(lines),
                    "containers": len(services),
                    "error_lines": sum(errors.values()),
                    "rank": ringc.rank_of(verdict["candidates"], [fault.service]),
                    "rank_most_errors": ringc.rank_of(
                        [name for name, _ in errors.most_common()], [fault.service]
                    ),
                    "rank_most_changed": ringc.rank_of(
                        rcaeval.most_changed(split.services_before, split.services_after),
                        [fault.service],
                    ),
                    **verdict,
                }
            )
        if progress:
            progress(f"{fault.id}: {rows[-1]['severity'] if rows else '-'}")
    return rows


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return dict(MISSING)
    summary = rcaeval.summarize(rows)
    summary["source"] = "Nezha's Online Boutique data (faults injected into the shop's pods)"
    summary["citation"] = data.NEZHA_CITATION
    summary["window_min"] = WINDOW_MIN
    summary["days"] = sorted({r["day"] for r in rows})
    summary["times_disagree"] = len({r["case"] for r in rows if r.get("times_apart_s")})
    return summary
