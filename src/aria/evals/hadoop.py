"""Failed Hadoop jobs on a real cluster: does ARIA tell them from healthy runs, and how does it
explain them?

Loghub Hadoop (Lin et al., "Log Clustering based Problem Identification for Online Service
Systems", ICSE-SEIP 2016): every container log of 55 MapReduce jobs (WordCount and PageRank).
Some ran normally; in the rest a failure was injected while they ran: a machine shut down, a
network disconnection, or a full disk. Each job's container logs are merged in time order (a
stack trace stays with the line that started it) and triaged offline, end to end, as one run
with the default per-run line cap. ARIA never sees the label.

Measured per label: the severity ARIA gave each job, and the failure mode of its leading
hypothesis. A job counts as flagged when ARIA rates it SEV1-SEV3. Baselines on the same jobs: a
rule that flags any job with an ERROR or FATAL line, and the keyword rule. ARIA's catalog has
modes for tasks that cannot reach the ResourceManager and for HDFS lease renewal failures, but
none for a full disk, so a disk-full job is explained right only by luck.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from aria.config import GuardrailConfig
from aria.contracts.inputs import RunOptions, TriageRequest
from aria.data.loghub import parse_raw_line
from aria.evals import metrics as m
from aria.evals.pipeline import EvalEnvironment
from aria.evals.severity import keyword_severity
from aria.severity.training import features_for

HADOOP_DIR = Path("data/raw/loghub-hadoop")
HADOOP_CITATION = (
    "Q. Lin, H. Zhang, J.-G. Lou, Y. Zhang, X. Chen. Log Clustering based Problem Identification "
    "for Online Service Systems. ICSE-SEIP 2016."
)
LABELS = {
    "normal": "normal",
    "machine down": "machine_down",
    "network disconnection": "network_disconnection",
    "disk full": "disk_full",
}
FLAGGED = {"SEV1", "SEV2", "SEV3"}
_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) ")
_ERROR = re.compile(r"^\S+ \S+ (ERROR|FATAL) ")


def find_labels(hadoop_dir: Path = HADOOP_DIR) -> Path | None:
    return next((p for p in hadoop_dir.rglob("abnormal_label.txt") if p.is_file()), None)


def read_labels(path: Path) -> dict[str, tuple[str, str]]:
    """Application id -> (application, label) from Loghub's abnormal_label.txt."""
    jobs: dict[str, tuple[str, str]] = {}
    application, label = "", ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("###"):
            application = line.lstrip("#").strip()
        elif line.endswith(":") and line[:-1].strip().lower() in LABELS:
            label = LABELS[line[:-1].strip().lower()]
        elif line.startswith("+") and label:
            jobs[line.lstrip("+ ").strip()] = (application, label)
    return jobs


def job_lines(directory: Path) -> list[str]:
    """Every container log of one job, merged in time order; continuation lines stay attached."""
    # "2015-10-17 15:37:56,547" sorts as text in time order.
    groups: list[tuple[str, int, list[str]]] = []
    order = 0
    for log in sorted(directory.glob("*.log")):
        current: list[str] | None = None
        for raw in log.read_text(encoding="utf-8", errors="replace").splitlines():
            stamp = _STAMP.match(raw)
            if stamp:
                current = [raw]
                groups.append((stamp.group(1), order, current))
                order += 1
            elif current is not None and raw.strip():
                current.append(raw)
    groups.sort(key=lambda g: (g[0], g[1]))
    return [line for _, _, lines in groups for line in lines]


def detection(flags: Sequence[bool], failed: Sequence[bool]) -> dict[str, Any]:
    tp = sum(f and b for f, b in zip(flags, failed, strict=True))
    fp = sum(f and not b for f, b in zip(flags, failed, strict=True))
    n_failed, n_normal = sum(failed), len(failed) - sum(failed)
    return {
        "failed_flagged": tp,
        "failed": n_failed,
        "recall": round(tp / max(1, n_failed), 4),
        "recall_ci95": m.exact_interval(tp, n_failed),
        "normal_flagged": fp,
        "normal": n_normal,
        "false_alarm_rate": round(fp / max(1, n_normal), 4),
    }


async def evaluate(
    env: EvalEnvironment,
    hadoop_dir: Path = HADOOP_DIR,
    *,
    known: Sequence[str] = (),
    pool: set[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    labels_path = find_labels(hadoop_dir)
    if labels_path is None:
        return {"missing": "download it with: aria data download --source loghub-hadoop"}
    jobs = read_labels(labels_path)
    root = labels_path.parent
    cap = GuardrailConfig().max_lines
    rows: list[dict[str, Any]] = []
    for job, (application, label) in sorted(jobs.items()):
        directory = root / job
        if not directory.is_dir():
            continue
        lines = job_lines(directory)
        outcome = await env.runner.start(
            TriageRequest(
                system="hadoop",
                title=f"{application} job {job}",
                logs=lines,
                options=RunOptions(use_llm=False),
            ),
            trigger="eval",
        )
        values = (await env.runner.snapshot(outcome.run_id)).values
        investigation = values.get("investigation") or {}
        leading = next(
            (
                h
                for h in investigation.get("hypotheses", [])
                if h.get("id") == investigation.get("leading_hypothesis")
            ),
            None,
        )
        severity = str((values.get("severity") or {}).get("severity", ""))
        rows.append(
            {
                "job": job,
                "application": application,
                "label": label,
                "lines": len(lines),
                "severity": severity,
                "leading_mode": (leading or {}).get("failure_mode") or "none",
                "any_error": any(_ERROR.match(line) for line in lines),
                "pool_lines": sum(
                    1 for line in lines if parse_raw_line("hadoop", line).message in (pool or ())
                ),
                "keyword": keyword_severity(features_for("hadoop", lines[:cap], known)),
            }
        )
        if progress:
            progress(f"{job} ({label}): {severity}, {rows[-1]['leading_mode']}")
    failed = [r["label"] != "normal" for r in rows]
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_label[row["label"]].append(row)
    return {
        "source": "Loghub Hadoop: container logs of 55 MapReduce jobs with injected failures",
        "citation": HADOOP_CITATION,
        "jobs": len(rows),
        "by_label": {k: len(v) for k, v in sorted(by_label.items())},
        "lines": sum(r["lines"] for r in rows),
        "line_cap": cap,
        "capped_jobs": sum(1 for r in rows if r["lines"] > cap),
        "overlap_with_training_sample": round(
            sum(r["pool_lines"] for r in rows) / max(1, sum(r["lines"] for r in rows)), 4
        ),
        "aria": detection([r["severity"] in FLAGGED for r in rows], failed),
        "baselines": {
            "any_error_line": detection([r["any_error"] for r in rows], failed),
            "keyword": detection([r["keyword"] in FLAGGED for r in rows], failed),
        },
        "severity_by_label": {
            k: dict(sorted(Counter(r["severity"] for r in v).items()))
            for k, v in sorted(by_label.items())
        },
        "leading_mode_by_label": {
            k: dict(Counter(r["leading_mode"] for r in v).most_common())
            for k, v in sorted(by_label.items())
        },
        "jobs_detail": rows,
    }
