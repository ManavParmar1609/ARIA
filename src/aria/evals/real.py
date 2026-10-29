"""Evaluation on real, labelled logs: lines no scenario builder composed, labels from experts.

HDFS (Xu et al., "Detecting Large-Scale System Problems by Mining Console Logs", SOSP 2009): the
first 104,815 lines of the log of a Hadoop cluster of more than 200 Amazon EC2 nodes (loglizer's
HDFS_100k sample) and the label Hadoop experts gave each block: Normal or Anomaly.

ARIA replays the log the way its periodic log scan would: overlapping windows, each parsed by the
production parser, which learns from the window which steps of a block's life come in equal
numbers and flags blocks that break them (parsing/flows.py). ARIA never sees a label. Each block
is judged in the first window that saw it from start to finish; blocks that started too close to
either end of the sample are not judged, and are counted.

The cluster logged about 7,500 lines a minute, more than a run's default line cap (20,000, a
guardrail each deployment sets) allows in a window of useful length, so the replay raises the
cap to ``MAX_LINES``.

Visible trace: some blocks the experts labelled Anomaly look exactly like a healthy block within
the sample: the same steps, the same number of times (their trouble shows later in the full log).
Nothing that reads only these lines can tell them apart, so the suite also reports recall on the
failures that leave a visible trace. That uses the labels to describe the data, never to tune ARIA.

Baselines, on each judged block's own lines: ARIA's severity engine as it was before lifecycle
checks (it sees failures that log an error-like line), and a keyword rule. The step-pair support
ARIA needs is varied to show the result does not hang on one setting.
"""

from __future__ import annotations

import bisect
import csv
import dataclasses
import gzip
import io
import re
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from aria.config import GuardrailConfig
from aria.contracts.base import Severity
from aria.data.loghub import LogRecord, format_raw_line, record_from_fields
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

HDFS_DIR = Path("data/raw/hdfs-100k")
HDFS_FIXTURE = Path("tests/fixtures/real/hdfs")
WINDOW_MIN = 15
STEP_MIN = 5
MAX_LINES = 150_000
SUPPORTS = (0.9, 0.95, 0.98)
SETTLE_QUANTILES = (0.99, 0.999)
SALT = b"aria-eval-real"
_BLOCK = re.compile(r"blk_-?\d+")
CITATION = (
    "W. Xu, L. Huang, A. Fox, D. Patterson, M. I. Jordan. Detecting Large-Scale System Problems "
    "by Mining Console Logs. SOSP 2009."
)


@dataclass
class HdfsSample:
    records: list[LogRecord]
    anomalous: dict[str, bool]  # block id -> labelled Anomaly by the experts
    source: str
    fixture: bool
    blocks: dict[str, list[int]] = field(default_factory=dict)  # block id -> record indices

    def __post_init__(self) -> None:
        for i, rec in enumerate(self.records):
            for block in set(_BLOCK.findall(rec.message)):
                self.blocks.setdefault(block, []).append(i)


def _rows(path: Path) -> Iterator[dict[str, str]]:
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as raw, io.TextIOWrapper(raw, encoding="utf-8") as text:
            yield from csv.DictReader(text)
    else:
        with path.open(newline="", encoding="utf-8") as handle:
            yield from csv.DictReader(handle)


def load_hdfs(directory: Path, *, fixture: bool = False) -> HdfsSample | None:
    """The structured HDFS lines and the experts' block labels, if downloaded."""
    structured = next(
        (p for p in sorted(directory.rglob("*.log_structured.csv*")) if "HDFS" in p.name), None
    )
    labels_path = next(directory.rglob("anomaly_label.csv"), None)
    if structured is None or labels_path is None:
        return None
    records = [record_from_fields("hdfs", int(r["LineId"]), r) for r in _rows(structured)]
    records = sorted(
        (r for r in records if r.ts is not None),
        key=lambda r: (r.ts.timestamp() if r.ts else 0.0, r.line_no),
    )
    anomalous = {row["BlockId"]: row["Label"] == "Anomaly" for row in _rows(labels_path)}
    return HdfsSample(records, anomalous, source=str(structured), fixture=fixture)


def find_hdfs(hdfs_dir: Path = HDFS_DIR) -> HdfsSample | None:
    """The full sample when downloaded, otherwise the committed fixture (not for measurement)."""
    return load_hdfs(hdfs_dir) or load_hdfs(HDFS_FIXTURE, fixture=True)


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
    """Parse overlapping windows as the log scan would; judge each block in its first window."""
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
        "precision_ci95": m.bootstrap(_precision, truth, flagged),
        "recall": round(_recall(truth, flagged), 4),
        "recall_ci95": m.bootstrap(_recall, truth, flagged),
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
    judged = sorted(b for b in verdicts if b in sample.anomalous)
    truth = [sample.anomalous[b] for b in judged]
    flagged = [verdicts[b] is not None for b in judged]
    if progress:
        progress(f"judged {len(judged)} blocks in {len(run.windows)} windows")

    # Healthy blocks ARIA judged: blocks cut off by either end of the sample are left out, so a
    # half-logged healthy block cannot make a failure look healthy.
    healthy = {signature(sample, b) for b, bad in zip(judged, truth, strict=True) if not bad}
    visible = [
        b for b, t in zip(judged, truth, strict=True) if t and signature(sample, b) not in healthy
    ]
    caught = [verdicts[b] for b in judged if sample.anomalous[b] and verdicts[b] is not None]
    false_alarms = [verdicts[b] for b in judged if not sample.anomalous[b] and verdicts[b]]
    missed_visible = [b for b in visible if verdicts[b] is None]
    baselines = per_block_baselines(sample, judged, engine, known)

    all_blocks = [b for b in sample.blocks if b in sample.anomalous]
    stamps = [r.ts for r in sample.records if r.ts is not None]
    result: dict[str, Any] = {
        "source": "loglizer HDFS_100k sample of HDFS_v1 (Loghub)",
        "citation": CITATION,
        "fixture": sample.fixture,
        "lines": len(sample.records),
        "minutes": round((stamps[-1] - stamps[0]).total_seconds() / 60, 1),
        "blocks": len(all_blocks),
        "anomalous_blocks": sum(1 for b in all_blocks if sample.anomalous[b]),
        "replay": {
            "window_min": window_min,
            "step_min": step_min,
            "windows": len(run.windows),
            "max_lines": MAX_LINES,
            "min_support": run.default[0],
            "settle_quantile": run.default[1],
        },
        "judged": len(judged),
        "judged_anomalous": sum(truth),
        "lifecycle": _detection(truth, flagged),
        "visible": {
            "anomalous": len(visible),
            "caught": len(visible) - len(missed_visible),
            "recall": round((len(visible) - len(missed_visible)) / max(1, len(visible)), 4),
            "look_healthy": sum(truth) - len(visible),
        },
        "baselines": {name: _detection(truth, flags) for name, flags in baselines.items()},
        "sensitivity": [_sensitivity(sample, run, setting) for setting in sorted(run.verdicts)],
        "caught_by": dict(Counter(f.problem for f in caught if f)),
        "top_patterns": [
            {"pattern": p, "blocks": n}
            for p, n in Counter(_pattern(f, run.templates) for f in caught if f).most_common(6)
        ],
        "false_alarms": [
            {"block": f.key, "reason": f.reason} for f in false_alarms[:10] if f is not None
        ],
        "missed_visible": [
            {
                "block": b,
                "steps": [f"{n} × {t}" for t, n in signature(sample, b)][:8],
            }
            for b in missed_visible[:10]
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
