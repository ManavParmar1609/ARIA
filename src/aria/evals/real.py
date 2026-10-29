"""Evaluation on real, labelled logs: lines no scenario builder composed, labels from experts.

HDFS (Xu et al., "Detecting Large-Scale System Problems by Mining Console Logs", SOSP 2009): loglizer's
HDFS_100k sample of the log of a Hadoop cluster of more than 200 Amazon EC2 nodes, and the label
Hadoop experts gave each block: Normal or Anomaly. The sample is the first 100,000 lines of the
log plus the later lines of the blocks those lines started (no block starts after line 100,000),
so its last stretch holds only those blocks. The suite reports results with and without it.

The replay is an offline run of the lifecycle check, not of the deployed log scan: overlapping
windows, each parsed by the production parser, which learns from the window which steps of a
block's life come in equal numbers and flags blocks that break them (parsing/flows.py). ARIA never
sees a label. Each block is judged in the first window that saw it from start to finish; blocks
that started too close to either end of a window are not judged, and are counted. (The deployed
scan opens a run on a burst of ERROR or FATAL lines; this log has none.)

The cluster logged several thousand lines a minute, more than a run's default line cap (a
guardrail each deployment sets) allows in a window of useful length, so the replay raises the
cap to ``MAX_LINES``.

Recall is reported both on the judged blocks and on every labelled failure in the sample, with
exact (Clopper-Pearson) intervals. The misses are described by their step counts: every failure
ARIA missed takes exactly the steps, the same number of times, of one of the commonest healthy
patterns, so step counts alone cannot set it apart.

Baselines on the same judged blocks, none fitted on labels: a rare-pattern rule, count-equality
pairs mined over the whole sample, PCA on event counts (Xu et al. 2009, as loglizer implements
it), an isolation forest, ARIA's severity engine on each block's own lines, and a keyword rule.
The window length and the two settings of the check are varied to show how much the result
depends on them.
"""

from __future__ import annotations

import bisect
import dataclasses
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest

from aria.config import GuardrailConfig
from aria.contracts.base import Severity
from aria.data.loghub import format_raw_line
from aria.data.real import HDFS_CITATION, HDFS_DIR, HDFS_FIXTURE, HdfsSample, find_hdfs, load_hdfs
from aria.evals import metrics as m
from aria.evals.severity import keyword_severity
from aria.evidence import EvidenceStore
from aria.parsing.flows import (
    BrokenUnit,
    FlowSettings,
    Step,
    check_flows,
    load_flow_settings,
    short_step,
)
from aria.parsing.parser import parse_lines
from aria.severity.engine import SeverityEngine
from aria.severity.policy import decide
from aria.severity.training import features_for

WINDOW_MIN = 15
STEP_MIN = 5
MAX_LINES = 150_000
SUPPORTS = (0.9, 0.95, 0.98)
SETTLE_QUANTILES = (0.99, 0.999)
WINDOW_LENGTHS = (5, 10, 15, 20)
# loglizer's HDFS_100k: the first 100,000 lines of HDFS_v1, then later lines of the same blocks.
CONTIGUOUS_LINES = 100_000
RARE_SHARE = 0.01  # the rare-pattern baseline flags step counts fewer than 1% of blocks share
SALT = b"aria-eval-real"
_BLOCK = re.compile(r"blk_-?\d+")
__all__ = ["HDFS_DIR", "HDFS_FIXTURE", "HdfsSample", "evaluate_hdfs", "load_hdfs", "summarize"]


Setting = tuple[float, float]  # (min_support, settle_quantile)


@dataclass
class Replay:
    verdicts: dict[Setting, dict[str, BrokenUnit | None]]  # setting -> block -> finding or none
    windows: list[dict[str, Any]]
    templates: dict[str, str]  # template id -> text, across windows
    default: Setting


def replay(
    sample: HdfsSample,
    *,
    engine: SeverityEngine | None = None,
    known: Sequence[str] = (),
    window_min: float = WINDOW_MIN,
    step_min: float = STEP_MIN,
    max_lines: int = MAX_LINES,
    supports: Sequence[float] = SUPPORTS,
    settle_quantiles: Sequence[float] = SETTLE_QUANTILES,
) -> Replay:
    """Parse overlapping windows offline; judge each block in the first window that holds it."""
    base = load_flow_settings()
    default = (base.min_support, base.settle_quantile)
    grid = {(s, q) for s in supports for q in settle_quantiles} | {default}
    settings: dict[Setting, FlowSettings] = {
        (s, q): dataclasses.replace(base, min_support=s, settle_quantile=q) for s, q in sorted(grid)
    }
    verdicts: dict[Setting, dict[str, BrokenUnit | None]] = {key: {} for key in settings}
    templates: dict[str, str] = {}
    times = [r.ts for r in sample.records if r.ts is not None]
    raw = [format_raw_line(r) for r in sample.records]
    guard = GuardrailConfig(max_lines=max_lines)
    windows: list[dict[str, Any]] = []
    start, last = times[0], times[-1]
    while start <= last:
        end = start + timedelta(minutes=window_min)
        lo, hi = bisect.bisect_left(times, start), bisect.bisect_left(times, end)
        out = parse_lines(
            raw[lo:hi],
            system="hdfs",
            guard=guard,
            evidence=EvidenceStore(),
            known_templates=known,
            salt=SALT,
        )
        steps = [
            Step(pl.idx, pl.record.ts, pl.template_id, pl.template, pl.record.message)
            for pl in out.lines
        ]
        templates.update(out.flows.templates)
        for setting, flow_settings in settings.items():
            result = out.flows if setting == default else check_flows(steps, flow_settings)
            found = {b.key: b for b in result.broken}
            for key in result.checked_keys:
                verdicts[setting].setdefault(key, found.get(key))
        window: dict[str, Any] = {
            "start": start.isoformat(),
            "lines": hi - lo,
            "blocks_seen": out.flows.units.get("HDFS block", 0),
            "blocks_judged": out.flows.n_checked,
            "blocks_flagged": len(out.flows.broken),
            "settle_s": out.flows.settle_s.get("HDFS block"),
        }
        if engine is not None:
            pre = engine.preliminary(out.batch.features, evidence=EvidenceStore())
            decision = decide(pre, gate=engine.gate, llm_unavailable_reason="offline evaluation")
            window |= {"severity": str(decision.severity), "decided_by": decision.decided_by}
        windows.append(window)
        if end > last:
            break
        start += timedelta(minutes=step_min)
    return Replay(verdicts, windows, templates, default)


def _detection(truth: Sequence[bool], flagged: Sequence[bool]) -> dict[str, Any]:
    tp = sum(1 for t, f in zip(truth, flagged, strict=True) if t and f)
    fp = sum(1 for t, f in zip(truth, flagged, strict=True) if f and not t)
    fn = sum(1 for t, f in zip(truth, flagged, strict=True) if t and not f)
    tn = len(truth) - tp - fp - fn
    return {
        "precision": round(_precision(truth, flagged), 4),
        "precision_ci95": m.exact_interval(tp, tp + fp),
        "recall": round(_recall(truth, flagged), 4),
        "recall_ci95": m.exact_interval(tp, tp + fn),
        "f1": round(_f1(truth, flagged), 4),
        "false_alarm_rate": round(fp / max(1, fp + tn), 4),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def _precision(truth: Sequence[bool], flagged: Sequence[bool]) -> float:
    hits = [t for t, f in zip(truth, flagged, strict=True) if f]
    return sum(hits) / len(hits) if hits else 0.0


def _recall(truth: Sequence[bool], flagged: Sequence[bool]) -> float:
    found = [f for t, f in zip(truth, flagged, strict=True) if t]
    return sum(found) / len(found) if found else 0.0


def _f1(truth: Sequence[bool], flagged: Sequence[bool]) -> float:
    p, r = _precision(truth, flagged), _recall(truth, flagged)
    return 2 * p * r / (p + r) if p + r else 0.0


def signature(sample: HdfsSample, block: str) -> tuple[tuple[str, int], ...]:
    """A block's steps and how often each occurred, by the experts' event templates."""
    counts = Counter(sample.records[i].gt_template or "?" for i in sample.blocks[block])
    return tuple(sorted(counts.items()))


def _pattern(finding: BrokenUnit, templates: dict[str, str]) -> str:
    """How a block broke, without its counts, so blocks that broke the same way group."""
    names = [short_step(templates.get(t, t)) for t in finding.steps]
    if finding.problem == "mismatch" and len(names) == 2:
        return f"fewer “{names[1]}” than “{names[0]}”"
    return f"a rare step: “{names[0]}”" if names else finding.reason


def _sensitivity(sample: HdfsSample, run: Replay, setting: Setting) -> dict[str, Any]:
    """Detection under another setting, on the blocks that setting judged."""
    verdicts = run.verdicts[setting]
    blocks = sorted(b for b in verdicts if b in sample.anomalous)
    found = _detection(
        [sample.anomalous[b] for b in blocks], [verdicts[b] is not None for b in blocks]
    )
    return {
        "min_support": setting[0],
        "settle_quantile": setting[1],
        "judged": len(blocks),
        **{k: found[k] for k in ("precision", "recall", "f1", "tp", "fp")},
    }


def per_block_baselines(
    sample: HdfsSample, blocks: Sequence[str], engine: SeverityEngine, known: Sequence[str]
) -> dict[str, list[bool]]:
    """Each block's own lines through ARIA's engine (no lifecycle check) and a keyword rule."""
    engine_flags, keyword_flags = [], []
    for block in blocks:
        lines = [format_raw_line(sample.records[i]) for i in sample.blocks[block]]
        feats = features_for("hdfs", lines, known)
        pre = engine.preliminary(feats, evidence=EvidenceStore())
        decision = decide(pre, gate=engine.gate, llm_unavailable_reason="offline evaluation")
        engine_flags.append(decision.severity != Severity.SEV4)
        keyword_flags.append(keyword_severity(feats) != str(Severity.SEV4))
    return {"engine_per_block": engine_flags, "keyword_per_block": keyword_flags}


def _event_counts(sample: HdfsSample, blocks: Sequence[str]) -> np.ndarray:
    """How often each of the experts' event templates occurs in each block (rows follow blocks)."""
    events = sorted(
        {sample.records[i].gt_template or "?" for b in blocks for i in sample.blocks[b]}
    )
    column = {e: j for j, e in enumerate(events)}
    counts = np.zeros((len(blocks), len(events)))
    for row, block in enumerate(blocks):
        for i in sample.blocks[block]:
            counts[row, column[sample.records[i].gt_template or "?"]] += 1
    return counts


def _pca_outliers(counts: np.ndarray, *, variance: float = 0.95, c_alpha: float = 3.2905) -> Any:
    """PCA anomaly detection on event counts (Xu et al. 2009), with loglizer's defaults.

    Tf-idf weighting, the principal subspace that holds 95% of the variance, and the
    Q-statistic threshold for a false-alarm rate of 0.001 on the residual.
    """
    n, width = counts.shape
    idf = np.log(n / ((counts > 0).sum(axis=0) + 1e-8))
    weighted = counts * idf
    centred = weighted - weighted.mean(axis=0)
    u, s, _ = np.linalg.svd(centred.T @ centred / n)
    k = int(np.searchsorted(np.cumsum(s) / s.sum(), variance)) + 1
    residual = np.eye(width) - u[:, :k] @ u[:, :k].T
    phi = [float((s[k:] ** (i + 1)).sum()) for i in range(3)]
    if phi[0] <= 0:
        return np.zeros(n, dtype=bool)
    h0 = 1.0 - 2 * phi[0] * phi[2] / (3.0 * phi[1] ** 2)
    threshold = phi[0] * (
        c_alpha * np.sqrt(2 * phi[1] * h0**2) / phi[0] + 1.0 + phi[1] * h0 * (h0 - 1) / phi[0] ** 2
    ) ** (1.0 / h0)
    return ((centred @ residual.T) ** 2).sum(axis=1) > threshold


def log_baselines(
    sample: HdfsSample, judged: Sequence[str], *, min_support: float
) -> dict[str, list[bool]]:
    """Standard unsupervised log-anomaly detectors, fitted on every block, scored on ``judged``.

    None uses a label. They read the experts' event templates (a cleaner parse than ARIA's own)
    and the whole sample at once, where ARIA sees one window at a time, so they start ahead.
    """
    blocks = sorted(b for b in sample.blocks if b in sample.anomalous)
    counts = _event_counts(sample, blocks)
    at = [{b: r for r, b in enumerate(blocks)}[b] for b in judged]
    signatures = {b: signature(sample, b) for b in blocks}
    share = Counter(signatures.values())
    held = counts > 0
    broken = np.zeros(len(blocks), dtype=bool)
    for a in range(counts.shape[1]):
        for b in range(a + 1, counts.shape[1]):
            either = held[:, a] | held[:, b]
            if (
                either.sum() >= 30
                and (counts[either, a] == counts[either, b]).mean() >= min_support
            ):
                broken |= either & (counts[:, a] != counts[:, b])
    forest = IsolationForest(random_state=0, contamination="auto").fit(counts)
    return {
        "rare_steps": [share[signatures[b]] / len(blocks) < RARE_SHARE for b in judged],
        "count_pairs": [bool(x) for x in broken[at]],
        "pca": [bool(x) for x in _pca_outliers(counts)[at]],
        "isolation_forest": [bool(x) for x in forest.predict(counts[at]) == -1],
    }


def _judged(sample: HdfsSample, run: Replay) -> tuple[list[str], list[bool], list[bool]]:
    verdicts = run.verdicts[run.default]
    judged = sorted(b for b in verdicts if b in sample.anomalous)
    truth = [sample.anomalous[b] for b in judged]
    return judged, truth, [verdicts[b] is not None for b in judged]


def _summary(truth: Sequence[bool], flagged: Sequence[bool], failures: int) -> dict[str, Any]:
    """Detection on the judged blocks, plus recall over every labelled failure in the sample."""
    found = _detection(truth, flagged)
    return {
        "judged": len(truth),
        **{k: found[k] for k in ("precision", "recall", "tp", "fp")},
        "recall_all": round(found["tp"] / max(1, failures), 4),
    }


def _contiguous(sample: HdfsSample, failures: int) -> dict[str, Any] | None:
    """The replay on the sample's contiguous head alone: the log as written, without the tail."""
    head = [r for r in sample.records if r.line_no <= CONTIGUOUS_LINES]
    if sample.fixture or len(head) == len(sample.records):
        return None
    part = HdfsSample(head, sample.anomalous, source=sample.source, fixture=False)
    _, truth, flagged = _judged(part, replay(part, supports=(), settle_quantiles=()))
    stamps = [r.ts for r in head if r.ts is not None]
    starts = {b: min(sample.records[i].line_no for i in idx) for b, idx in sample.blocks.items()}
    return {
        "lines": len(head),
        "minutes": round((stamps[-1] - stamps[0]).total_seconds() / 60, 1),
        "tail_lines": len(sample.records) - len(head),
        "tail_new_blocks": sum(1 for line in starts.values() if line > CONTIGUOUS_LINES),
        **_summary(truth, flagged, failures),
    }


def evaluate_hdfs(
    sample: HdfsSample,
    *,
    engine: SeverityEngine,
    known: Sequence[str] = (),
    pool_lines: set[str] | None = None,
    window_min: float = WINDOW_MIN,
    step_min: float = STEP_MIN,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    run = replay(sample, engine=engine, known=known, window_min=window_min, step_min=step_min)
    verdicts = run.verdicts[run.default]
    judged, truth, flagged = _judged(sample, run)
    if progress:
        progress(f"judged {len(judged)} blocks in {len(run.windows)} windows")

    all_blocks = [b for b in sample.blocks if b in sample.anomalous]
    failures = sum(1 for b in all_blocks if sample.anomalous[b])
    life = _detection(truth, flagged)
    caught = [verdicts[b] for b in judged if sample.anomalous[b] and verdicts[b] is not None]
    false_alarms = [verdicts[b] for b in judged if not sample.anomalous[b] and verdicts[b]]

    # What the misses look like: a failure whose steps, and how often each occurred, match those of
    # healthy blocks ARIA judged cannot be told apart by step counts. Blocks cut off by either end
    # of a window are left out, so a half-logged healthy block cannot make a failure look healthy.
    twins = Counter(signature(sample, b) for b, bad in zip(judged, truth, strict=True) if not bad)
    bad_blocks = [b for b, bad in zip(judged, truth, strict=True) if bad]
    distinct = [b for b in bad_blocks if not twins[signature(sample, b)]]
    look_alike = [b for b in bad_blocks if twins[signature(sample, b)]]
    missed = [b for b in bad_blocks if verdicts[b] is None]
    missed_twins = [twins[signature(sample, b)] for b in missed]

    baselines = per_block_baselines(sample, judged, engine, known) | log_baselines(
        sample, judged, min_support=run.default[0]
    )
    if progress:
        progress("baselines scored; replaying the contiguous head and other window lengths")
    lengths = [
        {
            "window_min": w,
            **_summary(
                *_judged(
                    sample,
                    run
                    if w == window_min
                    else replay(
                        sample,
                        window_min=w,
                        step_min=min(step_min, w),
                        supports=(),
                        settle_quantiles=(),
                    ),
                )[1:],
                failures,
            ),
        }
        for w in WINDOW_LENGTHS
    ]

    stamps = [r.ts for r in sample.records if r.ts is not None]
    per_minute = Counter(ts.replace(second=0, microsecond=0) for ts in stamps)
    result: dict[str, Any] = {
        "source": "loglizer HDFS_100k sample of HDFS_v1 (Loghub)",
        "citation": HDFS_CITATION,
        "fixture": sample.fixture,
        "lines": len(sample.records),
        "minutes": round((stamps[-1] - stamps[0]).total_seconds() / 60, 1),
        "blocks": len(all_blocks),
        "anomalous_blocks": failures,
        "peak_lines_per_min": max(per_minute.values(), default=0),
        "replay": {
            "window_min": window_min,
            "step_min": step_min,
            "windows": len(run.windows),
            "max_lines": MAX_LINES,
            "default_max_lines": GuardrailConfig().max_lines,
            "min_support": run.default[0],
            "settle_quantile": run.default[1],
        },
        "judged": len(judged),
        "judged_anomalous": sum(truth),
        "coverage": round(len(judged) / max(1, len(all_blocks)), 4),
        "lifecycle": life,
        "recall_all": round(life["tp"] / max(1, failures), 4),
        "recall_all_ci95": m.exact_interval(life["tp"], failures),
        "steps": {
            "distinct": {
                "failures": len(distinct),
                "caught": len(distinct) - sum(1 for b in distinct if verdicts[b] is None),
            },
            "look_alike": {
                "failures": len(look_alike),
                "caught": sum(1 for b in look_alike if verdicts[b] is not None),
            },
            "missed": {
                "failures": len(missed),
                "patterns": len({signature(sample, b) for b in missed}),
                "healthy_twins_min": min(missed_twins, default=0),
                "healthy_twins_max": max(missed_twins, default=0),
            },
        },
        "baselines": {name: _detection(truth, flags) for name, flags in baselines.items()},
        "contiguous": _contiguous(sample, failures),
        "window_lengths": lengths,
        "sensitivity": [_sensitivity(sample, run, setting) for setting in sorted(run.verdicts)],
        "caught_by": dict(Counter(f.problem for f in caught if f)),
        "top_patterns": [
            {"pattern": p, "blocks": n}
            for p, n in Counter(_pattern(f, run.templates) for f in caught if f).most_common(6)
        ],
        "false_alarms": [
            {"block": f.key, "reason": f.reason} for f in false_alarms[:10] if f is not None
        ],
        "windows": run.windows,
    }
    if pool_lines is not None:
        overlap = [r for r in sample.records if r.message in pool_lines]
        result["overlap_with_scenario_pool"] = {
            "lines": len(overlap),
            "blocks": len({b for r in overlap for b in _BLOCK.findall(r.message)}),
        }
    return result


def summarize(
    *,
    engine: SeverityEngine,
    known: Sequence[str] = (),
    hdfs_dir: Path = HDFS_DIR,
    pool_lines: set[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Every real source available; a source that is not downloaded is reported as missing."""
    sample = find_hdfs(hdfs_dir)
    if sample is None:
        return {"hdfs": {"missing": "download it with: aria data download --source hdfs-100k"}}
    return {
        "hdfs": evaluate_hdfs(
            sample, engine=engine, known=known, pool_lines=pool_lines, progress=progress
        )
    }
