"""Severity on the full BlueGene/L log, against the system administrators' alert tags.

BGL (Oliner & Stearley, "What Supercomputers Say", DSN 2007): every line LLNL's BlueGene/L logged
over 215 days, each tagged by the machine's administrators as an alert (with its category) or
not. The log is cut into contiguous 20-minute windows, the length of the training scenarios'
middle window. A window's label comes from its tags through the rubric that also labels the BGL
training scenarios (``config/labeling/bgl_alert_impact.yaml``); ARIA rates the window from its
lines alone, with the tags removed, through the production parser (and its default line cap),
the severity engine and the offline policy. Nothing here was tuned on this log.

The severity model was trained on semi-synthetic windows composed from Loghub's 2,000-line BGL
sample, which was drawn from this log, so the share of lines whose message also appears in the
sample is reported. Baselines on the same windows: the rules alone, the model alone, a keyword
rule, the highest log level in the window, and the commonest label.

Thunderbird, a Linux cluster at Sandia studied in the same paper, is scored the same way on the
stretch of its log that Loghub-2.0 publishes, read from the zip as it streams. Its tags are
labelled by a rubric written from what each tag's messages say, with BGL's window rules
(``config/labeling/thunderbird_alert_impact.yaml``); no training scenario was labelled with it.
"""

from __future__ import annotations

import dataclasses
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from aria.config import GuardrailConfig
from aria.contracts.base import Severity
from aria.contracts.parsing import WindowFeatures
from aria.data.labels import AlertRubric, label_window, load_rubric, tag_stats
from aria.data.loghub import LogRecord, format_raw_line, iter_raw_log
from aria.evals import metrics as m
from aria.evals.severity import keyword_severity
from aria.evidence import EvidenceStore
from aria.severity.engine import SeverityEngine
from aria.severity.policy import decide
from aria.severity.training import features_for

BGL_DIR = Path("data/raw/loghub-bgl")
BGL_CITATION = (
    "A. J. Oliner, J. Stearley. What Supercomputers Say: A Study of Five System Logs. DSN 2007."
)


@dataclasses.dataclass(frozen=True)
class TaggedLog:
    """A whole log whose lines carry administrators' alert tags, and how to read and label it."""

    system: str
    directory: Path
    name: str  # the log's file name, or the name of the zip that holds it
    member: str | None  # the log's path inside that zip
    rubric: Path
    source: str
    citation: str
    download: str  # the manifest source that fetches it

    def find(self, directory: Path | None = None) -> Path | None:
        return next(
            (p for p in (directory or self.directory).rglob(self.name) if p.is_file()), None
        )


BGL = TaggedLog(
    system="bgl",
    directory=BGL_DIR,
    name="BGL.log",
    member=None,
    rubric=Path("config/labeling/bgl_alert_impact.yaml"),
    source="Loghub BGL.log, the full BlueGene/L log with alert tags",
    citation=BGL_CITATION,
    download="loghub-bgl",
)
THUNDERBIRD = TaggedLog(
    system="thunderbird",
    directory=Path("data/raw/loghub2-thunderbird"),
    name="Thunderbird.zip",
    member="Thunderbird/Thunderbird_full.log",
    rubric=Path("config/labeling/thunderbird_alert_impact.yaml"),
    source="Loghub-2.0's Thunderbird log, with alert tags",
    citation=BGL_CITATION + " The log as Loghub-2.0 publishes it: Jiang et al., ISSTA 2024.",
    download="loghub2-thunderbird",
)
WINDOW_MIN = 20
SEVERE = {"SEV1", "SEV2"}
# The highest level a window holds, as the simplest severity rule an on-call team might write.
LEVEL_SEVERITY = {"FATAL": "SEV1", "ERROR": "SEV2", "WARN": "SEV3"}


@dataclasses.dataclass
class Window:
    start: datetime
    lines: list[str]  # raw lines with the alert tag replaced by "-"
    label: str
    top_level: str | None
    pool_lines: int


@dataclasses.dataclass
class _Tally:
    lines: int = 0
    without_time: int = 0
    alerts: int = 0
    first: datetime | None = None
    last: datetime | None = None


def find_bgl(bgl_dir: Path = BGL_DIR) -> Path | None:
    return BGL.find(bgl_dir)


def _start(ts: datetime) -> datetime:
    floored = ts.replace(second=0, microsecond=0)
    return floored - timedelta(minutes=floored.minute % WINDOW_MIN)


_RANK = {"FATAL": 0, "ERROR": 1, "WARN": 2}


def _window(start: datetime, group: Sequence[LogRecord], rubric: Any, pool: set[str]) -> Window:
    stats = tag_stats(((r.label or "", r.node) for r in group if r.label), rubric)
    severity, _ = label_window(stats, rubric)
    levels = [r.level for r in group if r.level in _RANK]
    return Window(
        start=start,
        # The tag is the label: ARIA's parser never reads it, and here it never gets it.
        lines=[format_raw_line(dataclasses.replace(r, label=None)) for r in group],
        label=str(severity),
        top_level=min(levels, key=_RANK.__getitem__) if levels else None,
        pool_lines=sum(1 for r in group if r.message in pool),
    )


def stream_windows(
    records: Iterable[LogRecord], pool: set[str], tally: _Tally, rubric: AlertRubric | None = None
) -> Iterator[Window]:
    """Contiguous windows, built as the log is read; lines without a timestamp are skipped.

    The log is in time order, but not strictly: a window stays open until the log is a full
    window past its end.
    """
    rubric = rubric or load_rubric()
    open_windows: dict[datetime, list[LogRecord]] = defaultdict(list)
    latest: datetime | None = None
    for record in records:
        tally.lines += 1
        tally.alerts += bool(record.label)
        if record.ts is None:
            tally.without_time += 1
            continue
        tally.first = min(tally.first or record.ts, record.ts)
        tally.last = max(tally.last or record.ts, record.ts)
        start = _start(record.ts)
        open_windows[start].append(record)
        if latest is None or start > latest:
            latest = start
            for done in sorted(
                s for s in open_windows if s < start - timedelta(minutes=WINDOW_MIN)
            ):
                yield _window(done, open_windows.pop(done), rubric, pool)
    for done in sorted(open_windows):
        yield _window(done, open_windows.pop(done), rubric, pool)


def _features(system: str, lines: Sequence[str], known: Sequence[str]) -> WindowFeatures:
    return features_for(system, lines, known)


def _batches(items: Iterable[Window], size: int) -> Iterator[list[Window]]:
    batch: list[Window] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _scores(truth: Sequence[str], pred: Sequence[str]) -> dict[str, Any]:
    severe = [(t, p) for t, p in zip(truth, pred, strict=True) if t in SEVERE]
    calm = [p for t, p in zip(truth, pred, strict=True) if t == str(Severity.SEV4)]
    return {
        "accuracy": round(m.accuracy(truth, pred), 4),
        "accuracy_ci95": m.bootstrap(m.accuracy, truth, pred),
        "macro_f1": round(m.macro_f1(truth, pred), 4),
        "macro_f1_ci95": m.bootstrap(m.macro_f1, truth, pred),
        "severe_under_triage": round(m.severe_under_triage(truth, pred), 4),
        "severe_missed": sum(1 for _, p in severe if p not in SEVERE),
        "quiet_paged": sum(1 for p in calm if p in SEVERE),
        "recall": {
            c: round(
                sum(t == p == c for t, p in zip(truth, pred, strict=True)) / max(1, truth.count(c)),
                4,
            )
            for c in sorted(set(truth))
        },
    }


@dataclasses.dataclass
class _Judged:
    label: str
    aria: str
    rules: str
    model: str
    keyword: str
    highest_level: str
    prediction_set: list[str]
    needs_review: bool
    lines: int
    pool_lines: int
    fired: tuple[str, ...]  # the rules that fired, to explain the misses


def _judge(engine: SeverityEngine, window: Window, feats: WindowFeatures) -> _Judged:
    pre = engine.preliminary(feats, evidence=EvidenceStore())
    decision = decide(pre, gate=engine.gate, llm_unavailable_reason="offline evaluation")
    probabilities = {str(k): v for k, v in pre.probabilities.items()}
    return _Judged(
        label=window.label,
        aria=str(decision.severity),
        rules=str(pre.rule_severity),
        model=max(probabilities, key=probabilities.__getitem__),
        keyword=keyword_severity(feats),
        highest_level=LEVEL_SEVERITY.get(window.top_level or "", "SEV4"),
        prediction_set=[str(x) for x in pre.prediction_set],
        needs_review=decision.needs_review,
        lines=len(window.lines),
        pool_lines=window.pool_lines,
        fired=tuple(hit.rule_id for hit in pre.rule_hits),
    )


def evaluate(
    path: Path,
    *,
    engine: SeverityEngine,
    known: Sequence[str],
    pool: set[str],
    workers: int = 1,
    batch: int = 256,
    progress: Callable[[str], None] | None = None,
    log: TaggedLog = BGL,
) -> dict[str, Any]:
    tally = _Tally()
    judged: list[_Judged] = []
    records = iter_raw_log(log.system, path, member=log.member)
    stream = stream_windows(records, pool, tally, load_rubric(log.rubric))
    executor = (
        ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn"))
        if workers > 1
        else None
    )
    try:
        for chunk in _batches(stream, batch):
            if executor is not None:
                features = list(
                    executor.map(
                        _features,
                        [log.system] * len(chunk),
                        [w.lines for w in chunk],
                        [known] * len(chunk),
                        chunksize=8,
                    )
                )
            else:
                features = [_features(log.system, w.lines, known) for w in chunk]
            judged += [_judge(engine, w, f) for w, f in zip(chunk, features, strict=True)]
            if progress and len(judged) % (batch * 8) < batch:
                progress(f"{len(judged):,} windows, {tally.lines:,} lines read")
    finally:
        if executor is not None:
            executor.shutdown()
    truth = [j.label for j in judged]
    common = Counter(truth).most_common(1)[0][0] if truth else "SEV4"
    methods = {
        "aria_policy": [j.aria for j in judged],
        "rules_only": [j.rules for j in judged],
        "model_only": [j.model for j in judged],
        "keyword": [j.keyword for j in judged],
        "highest_level": [j.highest_level for j in judged],
        "majority_class": [common] * len(judged),
    }
    cap = GuardrailConfig().max_lines
    auto = [j for j in judged if not j.needs_review]
    # What made ARIA page on windows the tags call quiet: the rules that fired there most often.
    paged_quiet = [j for j in judged if j.label == str(Severity.SEV4) and j.aria in SEVERE]
    quiet_rules = Counter(rule for j in paged_quiet for rule in set(j.fired)).most_common(5)
    placed = tally.lines - tally.without_time
    days = (
        (tally.last - tally.first).total_seconds() / 86_400 if tally.first and tally.last else 0.0
    )
    return {
        "system": log.system,
        "source": log.source,
        "citation": log.citation,
        "lines": tally.lines,
        "lines_without_time": tally.without_time,
        "alert_lines": tally.alerts,
        "days": round(days, 1),
        "window_min": WINDOW_MIN,
        "windows": len(judged),
        "labels": dict(sorted(Counter(truth).items())),
        "windows_over_line_cap": sum(1 for j in judged if j.lines > cap),
        "line_cap": cap,
        "methods": {name: _scores(truth, pred) for name, pred in methods.items()},
        "conformal": {
            "target_coverage": round(1 - engine.alpha, 4),
            "coverage": round(m.set_coverage([j.prediction_set for j in judged], truth), 4),
            "mean_set_size": round(
                sum(len(j.prediction_set) for j in judged) / max(1, len(judged)), 3
            ),
        },
        "automation": {
            "auto_decided": round(len(auto) / max(1, len(judged)), 4),
            "accuracy_when_auto": round(
                m.accuracy([j.label for j in auto], [j.aria for j in auto]), 4
            )
            if auto
            else None,
        },
        "confusion": {"classes": m.CLASSES, "matrix": m.confusion(truth, methods["aria_policy"])},
        "rules_on_paged_quiet_windows": [[rule, n] for rule, n in quiet_rules],
        "overlap_with_training_sample": {
            "lines": sum(j.pool_lines for j in judged),
            "share": round(sum(j.pool_lines for j in judged) / max(1, placed), 4),
        },
        "model_version": engine.model.version if engine.model else None,
    }


def summarize(
    *,
    engine: SeverityEngine,
    known: Sequence[str],
    pool: set[str],
    bgl_dir: Path | None = None,
    workers: int = 1,
    progress: Callable[[str], None] | None = None,
    log: TaggedLog = BGL,
) -> dict[str, Any]:
    path = log.find(bgl_dir)
    if path is None:
        return {"missing": f"download it with: aria data download --source {log.download}"}
    return evaluate(
        path, engine=engine, known=known, pool=pool, workers=workers, progress=progress, log=log
    )
