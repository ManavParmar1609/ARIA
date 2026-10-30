"""Bugs injected into OpenStack: does ARIA flag the runs that failed, including the ones no API
error told the user about, and leave the healthy runs alone?

The dessertlab fault-injection dataset (Cotroneo et al., "How Bad Can a Bug Get? An Empirical
Analysis of Software Failures in the OpenStack Cloud Computing Platform", ESEC/FSE 2019): 911
experiments. In each, one bug was injected into Nova, Cinder or Neutron (a wrong return value, a
missing call, a thrown exception, wrong or missing parameters) and a workload then created and
used VMs, volumes and networks. The labels say whether the run failed, the check that caught it,
and whether an API error reported it to the user. A healthy run is one whose bug caused no
failure.

Each experiment's faulty-round service logs (Nova, Cinder, Neutron, Glance and Heat) are merged in
time order, each line led by its file name as Loghub's OpenStack format expects (a traceback stays
with the line that started it), and triaged offline, end to end, as one run with the default
per-run line cap. ARIA never sees the label, the client's output or the injector's traces.

Measured: a run counts as flagged when ARIA rates it SEV1-SEV3, and as paged at SEV1-2. Recall on
the runs that failed, split by whether an API error reported the failure, and false alarms on the
healthy runs; how many runs ARIA was unsure of and sent to a reviewer at the most severe label in
its prediction set; and, free of any threshold, how well ARIA's probability of SEV1-2 ranks failed
runs above healthy ones (AUROC). Baselines on the same runs: a rule that flags any run with an
ERROR or CRITICAL line (and the count of such lines as its ranking), the keyword rule, and ARIA's
rules alone. The API error is the signal a user already had: it catches every reported failure by
definition and none of the silent ones.
"""

from __future__ import annotations

import csv
import gzip
import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sklearn.metrics import roc_auc_score

from aria.config import GuardrailConfig
from aria.contracts.inputs import RunOptions, TriageRequest
from aria.data.loghub import parse_raw_line
from aria.evals import metrics as m
from aria.evals.hadoop import FLAGGED, detection
from aria.evals.pipeline import EvalEnvironment
from aria.evals.severity import keyword_severity
from aria.severity.training import features_for

OPENSTACK_DIR = Path("data/raw/openstack-faults")
OPENSTACK_CITATION = (
    "D. Cotroneo, L. De Simone, P. Liguori, R. Natella, N. Bidokhti. How Bad Can a Bug Get? An "
    "Empirical Analysis of Software Failures in the OpenStack Cloud Computing Platform. "
    "ESEC/FSE 2019."
)
MISSING = {"missing": "download it with: aria data download --source openstack-faults"}
SUBSYSTEMS = ("Nova", "Cinder", "Neutron")
# Every service whose faulty-round log is fetched: Keystone, the client and the injector are not.
SERVICES = ("nova", "cinder", "neutron", "glance", "heat")
# A page: the level the BGL section counts as severe.
PAGED = {"SEV1", "SEV2"}
_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}) ")
_ERROR = re.compile(r"^\S+ \S+ \S+ \d+ (ERROR|CRITICAL) ")


@dataclass(frozen=True)
class Experiment:
    subsystem: str  # where the bug was injected: Nova, Cinder or Neutron
    test: str
    fault_type: str  # e.g. "wrong_return_value", from OPENSTACK_WRONG_RETURN_VALUE-NETWORK
    failed: bool
    check: str  # the check that caught the failure, e.g. "volume_attached"; "" if none did
    reported: bool  # an API error told the user


def _fault_type(raw: str) -> str:
    kind = raw.split("-", 1)[0].lower()
    return kind.removeprefix("openstack_") or "unknown"


def read_labels(root: Path = OPENSTACK_DIR) -> list[Experiment]:
    """One row per experiment from the dataset's nova.tsv, cinder.tsv and neutron.tsv."""
    experiments: list[Experiment] = []
    for subsystem in SUBSYSTEMS:
        path = root / f"{subsystem.lower()}.tsv"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                test = (row.get("TEST") or "").strip()
                if not test:
                    continue
                failed = (row.get("ROUND_1") or "").strip() == "FAILURE"
                check = (row.get("ASSERTION_R1") or "").strip()
                experiments.append(
                    Experiment(
                        subsystem=subsystem,
                        test=test,
                        fault_type=_fault_type(row.get("FAULT_TYPE") or ""),
                        failed=failed,
                        check=check.lower().removeprefix("failure_") if failed else "",
                        reported=failed and bool((row.get("API_R1") or "").strip()),
                    )
                )
    return experiments


def _read(path: Path) -> Iterator[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            yield raw.rstrip("\r\n")


def experiment_lines(test_dir: Path) -> list[str]:
    """The faulty round's service logs merged in time order, each line led by its file name;
    a traceback or a dump spread over several lines stays with the line that started it."""
    groups: list[tuple[str, int, list[str]]] = []
    order = 0
    round_dir = test_dir / "logs" / "round_1"
    for service in SERVICES:
        for path in sorted((round_dir / service).glob("*.log.bzip2.out*")):
            name = path.name.split(".log.", 1)[0] + ".log"  # nova-compute.log.bzip2.out.gz
            current: list[str] | None = None
            for raw in _read(path):
                stamp = _STAMP.match(raw)
                if stamp:
                    current = [f"{name} {raw}"]
                    groups.append((stamp.group(1), order, current))
                    order += 1
                elif current is not None and raw.strip():
                    current.append(raw)
    groups.sort(key=lambda g: (g[0], g[1]))
    return [line for _, _, lines in groups for line in lines]


async def triage(
    env: EvalEnvironment,
    picks: Sequence[int] | None = None,
    root: Path = OPENSTACK_DIR,
    *,
    known: Sequence[str] = (),
    pool: set[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> list[dict[str, Any]]:
    """One row per experiment at ``picks`` (positions in :func:`read_labels`; all by default).

    Runs pause at review and never publish, so none teaches the next what normal looks like:
    the experiments can be shared out across processes in any order.
    """
    experiments = read_labels(root)
    cap = GuardrailConfig().max_lines
    rows: list[dict[str, Any]] = []
    for index in range(len(experiments)) if picks is None else picks:
        experiment = experiments[index]
        lines = experiment_lines(root / experiment.subsystem / experiment.test)
        if not lines:
            continue
        outcome = await env.runner.start(
            TriageRequest(
                system="openstack",
                title=f"OpenStack {experiment.subsystem} experiment {experiment.test}",
                logs=lines,
                options=RunOptions(use_llm=False),
            ),
            trigger="eval",
        )
        values = (await env.runner.snapshot(outcome.run_id)).values
        # Scored once and never read again: a run's checkpoints hold every line it read, and 911
        # of them would fill tens of gigabytes.
        await env.runner.delete(outcome.run_id)
        investigation = values.get("investigation") or {}
        leading = next(
            (
                h
                for h in investigation.get("hypotheses", [])
                if h.get("id") == investigation.get("leading_hypothesis")
            ),
            None,
        )
        assessment = values.get("severity") or {}
        severity = str(assessment.get("severity", ""))
        probabilities = assessment.get("probabilities") or {}
        rows.append(
            {
                "index": index,
                "subsystem": experiment.subsystem,
                "test": experiment.test,
                "fault_type": experiment.fault_type,
                "failed": experiment.failed,
                "check": experiment.check,
                "reported": experiment.reported,
                "lines": len(lines),
                "severity": severity,
                "flagged": severity in FLAGGED,
                "rule_severity": str(assessment.get("rule_severity", "")),
                "decided_by": str(assessment.get("decided_by", "")),
                "needs_review": bool(assessment.get("needs_review")),
                "severe_probability": round(
                    float(probabilities.get("SEV1", 0.0)) + float(probabilities.get("SEV2", 0.0)),
                    6,
                ),
                "leading_mode": (leading or {}).get("failure_mode") or "none",
                "error_lines": sum(1 for line in lines if _ERROR.match(line)),
                "pool_lines": sum(
                    1 for line in lines if parse_raw_line("openstack", line).message in (pool or ())
                ),
                "keyword": keyword_severity(features_for("openstack", lines[:cap], known)),
            }
        )
        if progress:
            progress(f"{experiment.subsystem} {experiment.test}: {severity}")
    return rows


def _share(rows: Sequence[dict[str, Any]], flag: str) -> dict[str, Any]:
    hits = sum(1 for r in rows if r[flag])
    return {
        "flagged": hits,
        "of": len(rows),
        "share": round(hits / max(1, len(rows)), 4),
        "ci95": m.exact_interval(hits, len(rows)),
    }


def _auroc(failed: Sequence[bool], scores: Sequence[float]) -> float:
    return float(roc_auc_score(failed, scores)) if len(set(failed)) == 2 else 0.5


def _ranking(rows: Sequence[dict[str, Any]], score: str) -> dict[str, Any]:
    """How well ``score`` ranks the failed runs above the healthy ones, overall and for the
    silent failures alone."""
    out: dict[str, Any] = {}
    healthy = [r for r in rows if not r["failed"]]
    for name, group in (
        ("all", list(rows)),
        ("silent", [r for r in rows if r["failed"] and not r["reported"]] + healthy),
    ):
        truth = [bool(r["failed"]) for r in group]
        scores = [float(r[score]) for r in group]
        out[name] = {
            "auroc": round(_auroc(truth, scores), 4),
            "auroc_ci95": m.bootstrap(_auroc, truth, scores),
            "n": len(group),
        }
    return out


def summarize(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return dict(MISSING)
    cap = GuardrailConfig().max_lines
    failed = [r["failed"] for r in rows]
    reported = [r for r in rows if r["failed"] and r["reported"]]
    silent = [r for r in rows if r["failed"] and not r["reported"]]
    decided = [r for r in rows if not r["needs_review"]]
    by_subsystem: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_fault: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_subsystem[row["subsystem"]].append(row)
        by_fault[row["fault_type"]].append(row)
    return {
        "source": "the dessertlab OpenStack fault-injection dataset",
        "citation": OPENSTACK_CITATION,
        "experiments": len(rows),
        "by_subsystem": {k: len(v) for k, v in sorted(by_subsystem.items())},
        "failed": sum(failed),
        "reported": len(reported),
        "silent": len(silent),
        "lines": sum(r["lines"] for r in rows),
        "line_cap": cap,
        "capped": sum(1 for r in rows if r["lines"] > cap),
        "overlap_with_training_sample": round(
            sum(r["pool_lines"] for r in rows) / max(1, sum(r["lines"] for r in rows)), 4
        ),
        "aria": {
            **detection([r["flagged"] for r in rows], failed),
            "paged": detection([r["severity"] in PAGED for r in rows], failed),
            "reported": _share(reported, "flagged"),
            "silent": _share(silent, "flagged"),
            "ranking": _ranking(rows, "severe_probability"),
        },
        "review": {
            "failed": _share([r for r in rows if r["failed"]], "needs_review"),
            "healthy": _share([r for r in rows if not r["failed"]], "needs_review"),
            "decided_by": dict(Counter(r["decided_by"] for r in rows).most_common()),
            "decided": detection([r["flagged"] for r in decided], [r["failed"] for r in decided]),
        },
        "baselines": {
            "any_error_line": {
                **detection([r["error_lines"] > 0 for r in rows], failed),
                "reported": _share([{"hit": r["error_lines"] > 0} for r in reported], "hit"),
                "silent": _share([{"hit": r["error_lines"] > 0} for r in silent], "hit"),
                "ranking": _ranking(rows, "error_lines"),
            },
            "keyword": detection([r["keyword"] in FLAGGED for r in rows], failed),
            "rules_only": detection([r["rule_severity"] in FLAGGED for r in rows], failed),
        },
        "by_subsystem_detail": {
            k: detection([r["flagged"] for r in v], [r["failed"] for r in v])
            for k, v in sorted(by_subsystem.items())
        },
        "by_fault_type": {
            k: detection([r["flagged"] for r in v], [r["failed"] for r in v])
            for k, v in sorted(by_fault.items())
            if len(v) >= 20
        },
        "checks": dict(Counter(r["check"] for r in rows if r["failed"]).most_common()),
        "severity_by_outcome": {
            "failed": dict(sorted(Counter(r["severity"] for r in rows if r["failed"]).items())),
            "healthy": dict(
                sorted(Counter(r["severity"] for r in rows if not r["failed"]).items())
            ),
        },
        "leading_mode_by_outcome": {
            "failed": dict(Counter(r["leading_mode"] for r in rows if r["failed"]).most_common(8)),
            "healthy": dict(
                Counter(r["leading_mode"] for r in rows if not r["failed"]).most_common(8)
            ),
        },
    }


async def evaluate(
    env: EvalEnvironment,
    root: Path = OPENSTACK_DIR,
    *,
    known: Sequence[str] = (),
    pool: set[str] | None = None,
    limit: int | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Every experiment (or the first ``limit``) in one environment, summarized."""
    count = len(read_labels(root))
    if not count:
        return dict(MISSING)
    picks = range(count if limit is None else min(limit, count))
    return summarize(await triage(env, picks, root, known=known, pool=pool, progress=progress))
