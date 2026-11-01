"""Code-level faults in microservice shops: does ARIA flag the logs after a fault and leave the
logs before it alone, and does it name the service the fault was injected into?

RCAEval's RE3 suite (Pham et al., WWW 2025 Companion): 90 cases, 30 in each of three shops
(Sock Shop, Online Boutique, Train Ticket), each a code-level fault injected into one service.
Every case gives two windows: every service's logs from before the fault (healthy) and from
the fault on (faulty). Each window is triaged offline, end to end, as one run with the default
per-run line cap, its lines led by their container's name as a log collector forwards them. ARIA
never sees the case's label.

Measured: faulty windows flagged (SEV1-3) and healthy ones flagged (false alarms); in each case,
whether the faulty window was rated above its own healthy window; how well ARIA's probability of
SEV1-2 ranks faulty windows above healthy ones (AUROC); and whether the service at fault is
ARIA's first suspect, or among its first three (the leading hypothesis's component, the other
hypotheses' components by confidence, then the components carrying the window's signal).
Baselines on the same windows: a rule that flags any window with an error line; for naming,
the container with the most error lines in what ARIA read, the container whose share of the
lines changed most from the healthy window (it reads both windows, which ARIA does not), and a
container picked at random (its expected hit rate). Nothing was tuned on this data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from aria.config import GuardrailConfig
from aria.data import rcaeval as data
from aria.data.loghub import parse_generic_line
from aria.evals import ringc
from aria.evals.pipeline import EvalEnvironment

MISSING = {"missing": "download it with: aria data download --source rcaeval-re3"}
RUN_SYSTEM = {"SS": "sock-shop", "OB": "online-boutique", "TT": "train-ticket"}
ERRORS = {"ERROR", "FATAL"}


def _error_counts(lines: Sequence[str]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in lines:
        record = parse_generic_line("generic", line)
        if record.level in ERRORS and record.component:
            counts[record.component] += 1
    return counts


def _most_changed(before: dict[str, int], after: dict[str, int]) -> list[str]:
    """Containers by how far their share of the lines moved between the windows."""
    total_before = sum(before.values()) or 1
    total_after = sum(after.values()) or 1
    names = set(before) | set(after)
    change = {
        n: abs(after.get(n, 0) / total_after - before.get(n, 0) / total_before) for n in names
    }
    return sorted(names, key=lambda n: (-change[n], n))


async def triage(
    env: EvalEnvironment,
    picks: Sequence[int] | None = None,
    root: Path = data.RCAEVAL_DIR,
    *,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """Two rows per case at ``picks`` (positions in :func:`find_cases`): healthy, then faulty."""
    cases = data.find_cases(root)
    cap = GuardrailConfig().max_lines
    rows: list[dict[str, Any]] = []
    for index in range(len(cases)) if picks is None else picks:
        case = cases[index]
        split = data.windows(case)
        for window, lines, services in (
            ("healthy", split.before, split.services_before),
            ("faulty", split.after, split.services_after),
        ):
            if not lines:
                continue
            verdict = await ringc.triage(
                env,
                system=RUN_SYSTEM.get(case.system, "generic"),
                title=f"{data.SYSTEMS.get(case.system, case.system)} logs, case {index}",
                lines=lines,
            )
            read = lines[:cap]
            errors = _error_counts(read)
            ranked_errors = [name for name, _ in errors.most_common()]
            rows.append(
                {
                    "index": index,
                    "case": case.id,
                    "system": case.system,
                    "service": case.service,
                    "fault": case.fault,
                    "window": window,
                    "faulty": window == "faulty",
                    "lines": len(lines),
                    "containers": len(services),
                    "error_lines": sum(errors.values()),
                    "rank": ringc.rank_of(verdict["candidates"], [case.service]),
                    "rank_most_errors": ringc.rank_of(ranked_errors, [case.service]),
                    "rank_most_changed": ringc.rank_of(
                        _most_changed(split.services_before, split.services_after),
                        [case.service],
                    ),
                    **verdict,
                }
            )
        if progress:
            progress(f"{case.id}: {rows[-1]['severity'] if rows else '-'}")
    return rows


def _detection(
    rows: Sequence[dict[str, Any]], flag: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    faulty = [r for r in rows if r["faulty"]]
    healthy = [r for r in rows if not r["faulty"]]
    return {
        "faulty_flagged": ringc.share(sum(flag(r) for r in faulty), len(faulty)),
        "healthy_flagged": ringc.share(sum(flag(r) for r in healthy), len(healthy)),
    }


def _paired(rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    """Per case, the faulty window's level against its own healthy window's."""
    by_case: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        by_case[row["case"]][row["window"]] = row["severity"]
    out = {"higher": 0, "same": 0, "lower": 0}
    for pair in by_case.values():
        if "faulty" in pair and "healthy" in pair:
            a, b = ringc.ORDINAL[pair["faulty"]], ringc.ORDINAL[pair["healthy"]]
            out["higher" if a > b else "same" if a == b else "lower"] += 1
    return out


def _random_expected(rows: Sequence[dict[str, Any]], top: int) -> float:
    picks = [min(1.0, top / int(r["containers"])) for r in rows if r["containers"]]
    return round(sum(picks) / max(1, len(picks)), 4)


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return dict(MISSING)
    faulty = [r for r in rows if r["faulty"]]
    cases = sorted({r["case"] for r in rows})
    by_system: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_fault: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_system[row["system"]].append(row)
        by_fault[row["fault"]].append(row)
    truth = [bool(r["faulty"]) for r in rows]
    cap = GuardrailConfig().max_lines
    return {
        "source": "RCAEval RE3 (code-level faults in three microservice shops)",
        "citation": data.RCAEVAL_CITATION,
        "stamp": ringc.STAMP,
        "cases": len(cases),
        "windows": len(rows),
        "by_system": {k: len({r["case"] for r in v}) for k, v in sorted(by_system.items())},
        "lines": sum(r["lines"] for r in rows),
        "line_cap": cap,
        "windows_over_line_cap": sum(1 for r in rows if r["lines"] > cap),
        "aria": {
            **_detection(rows, lambda r: r["flagged"]),
            "paged": _detection(rows, lambda r: r["paged"]),
            "paired": _paired(rows),
            "ranking": ringc.ranking(truth, [r["severe_probability"] for r in rows]),
            "naming": ringc.localisation([r["rank"] for r in faulty]),
        },
        "baselines": {
            "any_error_line": _detection(rows, lambda r: r["error_lines"] > 0),
            "error_count_ranking": ringc.ranking(truth, [float(r["error_lines"]) for r in rows]),
            "naming_most_errors": ringc.localisation([r["rank_most_errors"] for r in faulty]),
            "naming_most_changed": ringc.localisation([r["rank_most_changed"] for r in faulty]),
            "naming_random_expected": {
                "top1": _random_expected(faulty, 1),
                "top3": _random_expected(faulty, 3),
            },
        },
        "by_system_detail": {
            k: {
                "cases": len({r["case"] for r in v}),
                **_detection(v, lambda r: r["flagged"]),
                "naming": ringc.localisation([r["rank"] for r in v if r["faulty"]]),
            }
            for k, v in sorted(by_system.items())
        },
        "by_fault": {
            k: {
                "cases": len({r["case"] for r in v}),
                **_detection(v, lambda r: r["flagged"]),
                "naming": ringc.localisation([r["rank"] for r in v if r["faulty"]]),
            }
            for k, v in sorted(by_fault.items())
        },
        "severity": {
            "faulty": ringc.by_level(faulty),
            "healthy": ringc.by_level([r for r in rows if not r["faulty"]]),
        },
        "review": {
            "faulty": ringc.share(sum(r["needs_review"] for r in faulty), len(faulty)),
            "healthy": ringc.share(
                sum(r["needs_review"] for r in rows if not r["faulty"]), len(rows) - len(faulty)
            ),
        },
        "leading_mode": dict(Counter(r["leading_mode"] for r in faulty).most_common(6)),
    }
