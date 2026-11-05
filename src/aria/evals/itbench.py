"""Kubernetes incidents: does ARIA treat each ITBench-Lite incident as one, and does it name the
service at fault rather than the one that raised the alert?

ITBench-Lite's 35 site-reliability scenarios (IBM Research): snapshots of a Kubernetes cluster
running the OpenTelemetry demo shop while one fault was injected (a bad feature flag, a broken
deployment, a namespace quota, an overloaded service, and so on). Each is triaged offline, end
to end, as one run, from what an on-call engineer is paged with: the Prometheus alerts in
alerting state when the incident was raised, and the 10 minutes of Kubernetes events and service
logs before it (at most the newest 20,000 log lines, kept by the download). ARIA never sees the
ground truth.

Every scenario is an incident, so there is no false-alarm rate here; that is measured on the
healthy windows of the RCAEval and AnoMod suites. Measured: scenarios flagged (SEV1-3) and paged
(SEV1-2); and whether ARIA's first suspect, or one of its first three, is a service at fault: a
workload marked as the root cause, or, when the root cause is not a workload (a ConfigMap, a
namespace quota, an autoscaler), the first workloads it spreads to. Baselines: the alerts' own
highest severity (critical pages, warning flags), the services the alerts name (critical first),
the service with the most error lines, and a service picked at random. Nothing was tuned on this
data.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from aria.config import GuardrailConfig
from aria.contracts.inputs import AlertSignal
from aria.data import itbench as data
from aria.data.loghub import parse_generic_line
from aria.evals import ringc
from aria.evals.pipeline import EvalEnvironment

MISSING = {"missing": "download it with: aria data download --source itbench-lite"}
WINDOW_MIN = 10  # minutes before the incident; the download keeps the same span of logs
SYSTEM = "otel-demo"
ERRORS = {"ERROR", "FATAL"}
_ALERT_LEVEL = {"critical": "SEV2", "warning": "SEV3"}
_RANK = {"critical": 0, "warning": 1}


def alert_severity(alerts: Sequence[AlertSignal]) -> str:
    """The alerts' own verdict: a critical alert pages, a warning flags."""
    labels = {(a.labels.get("severity") or "").lower() for a in alerts if a.status == "firing"}
    for label, level in _ALERT_LEVEL.items():
        if label in labels:
            return level
    return "SEV4"


def alerted_services(alerts: Sequence[AlertSignal]) -> list[str]:
    """The workloads the firing alerts name, critical alerts first."""
    out: list[str] = []
    ordered = sorted(
        (a for a in alerts if a.status == "firing"),
        key=lambda a: _RANK.get((a.labels.get("severity") or "").lower(), 2),
    )
    for alert in ordered:
        for key in ("service_name", "service", "deployment", "container", "pod"):
            value = alert.labels.get(key)
            if value and "prometheus" not in value:
                name = data.workload(value)
                if name not in out:
                    out.append(name)
    return out


async def triage(
    env: EvalEnvironment,
    picks: Sequence[int] | None = None,
    root: Path = data.ITBENCH_DIR,
    *,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """One row per scenario at ``picks`` (positions in :func:`find_scenarios`)."""
    scenarios = data.find_scenarios(root)
    cap = GuardrailConfig().max_lines
    rows: list[dict[str, Any]] = []
    for index in range(len(scenarios)) if picks is None else picks:
        scenario = scenarios[index]
        lines = data.scenario_lines(scenario, WINDOW_MIN)
        alerts = data.alerts(scenario)
        if not lines and not alerts:
            continue
        verdict = await ringc.triage(
            env,
            system=SYSTEM,
            title=f"Kubernetes incident, scenario {index}",
            lines=lines,
            alerts=alerts,
        )
        errors: Counter[str] = Counter()
        services: set[str] = set()
        for line in lines[:cap]:
            record = parse_generic_line("generic", line)
            if record.component:
                services.add(record.component)
                if record.level in ERRORS:
                    errors[record.component] += 1
        rows.append(
            {
                "index": index,
                "scenario": scenario.id,
                "categories": list(scenario.categories),
                "root_kinds": list(scenario.root_kinds),
                "targets": list(scenario.services),
                "alerts": len(alerts),
                "lines": len(lines),
                "services": len(services),
                "error_lines": sum(errors.values()),
                "alert_severity": alert_severity(alerts),
                "rank": ringc.rank_of(verdict["candidates"], scenario.services),
                "rank_alerted": ringc.rank_of(alerted_services(alerts), scenario.services),
                "rank_most_errors": ringc.rank_of(
                    [n for n, _ in errors.most_common()], scenario.services
                ),
                **verdict,
            }
        )
        if progress:
            progress(f"{scenario.id}: {verdict['severity']}")
    return rows


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return dict(MISSING)
    named = [r for r in rows if r["targets"]]
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        workload = any(k in data.WORKLOADS for k in row["root_kinds"])
        by_kind["workload" if workload else "not a workload"].append(row)
    random_top = {
        n: round(
            sum(min(1.0, n / r["services"]) for r in named if r["services"]) / max(1, len(named)),
            4,
        )
        for n in (1, 3)
    }
    return {
        "source": "ITBench-Lite's site-reliability scenarios (Kubernetes incidents)",
        "citation": data.ITBENCH_CITATION,
        "stamp": ringc.STAMP,
        "scenarios": len(rows),
        "window_min": WINDOW_MIN,
        "lines": sum(r["lines"] for r in rows),
        "line_cap": GuardrailConfig().max_lines,
        "with_named_service": len(named),
        "aria": {
            "flagged": ringc.share(sum(r["flagged"] for r in rows), len(rows)),
            "paged": ringc.share(sum(r["paged"] for r in rows), len(rows)),
            "missed": ringc.miss_rate(sum(not r["flagged"] for r in rows), len(rows)),
            "naming": ringc.localisation([r["rank"] for r in named]),
        },
        "baselines": {
            "alert_severity": {
                "flagged": ringc.share(
                    sum(r["alert_severity"] in ringc.FLAGGED for r in rows), len(rows)
                ),
                "paged": ringc.share(
                    sum(r["alert_severity"] in ringc.SEVERE for r in rows), len(rows)
                ),
            },
            "any_error_line": ringc.share(sum(r["error_lines"] > 0 for r in rows), len(rows)),
            "naming_alerted_service": ringc.localisation([r["rank_alerted"] for r in named]),
            "naming_most_errors": ringc.localisation([r["rank_most_errors"] for r in named]),
            "naming_random_expected": {f"top{n}": v for n, v in random_top.items()},
        },
        "by_root_kind": {
            kind: {
                "scenarios": len(v),
                "flagged": ringc.share(sum(r["flagged"] for r in v), len(v)),
                "naming": ringc.localisation([r["rank"] for r in v if r["targets"]]),
            }
            for kind, v in sorted(by_kind.items())
        },
        "by_category": dict(sorted(Counter(c for r in rows for c in r["categories"] if c).items())),
        "severity": ringc.by_level(rows),
        "review": ringc.share(sum(r["needs_review"] for r in rows), len(rows)),
        "leading_mode": dict(Counter(r["leading_mode"] for r in rows).most_common(6)),
    }
