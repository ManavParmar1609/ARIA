"""Window features: the computed signals the severity rules and model read."""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from aria.contracts.parsing import WindowFeatures
from aria.parsing.catalog import ServiceCatalog, load_catalog, load_lexicon

ERROR_LEVELS = frozenset({"ERROR", "FATAL"})
CRITICAL_COMPONENT = 0.8


@dataclass(slots=True)
class FeatureInput:
    """The minimum a feature needs to know about one parsed line."""

    ts: datetime | None
    node: str | None
    component: str | None
    level: str | None
    message: str
    template_id: str


def per_minute_counts(times: Sequence[datetime], start: datetime, end: datetime) -> list[int]:
    minutes = max(1, math.ceil((end - start).total_seconds() / 60) or 1)
    counts = [0] * minutes
    for ts in times:
        index = min(minutes - 1, max(0, int((ts - start).total_seconds() // 60)))
        counts[index] += 1
    return counts


def burst_score(error_counts: Sequence[int]) -> float:
    """How far the busiest minute sits above the typical one, as a Poisson z-score."""
    if not error_counts or max(error_counts) == 0:
        return 0.0
    baseline = max(statistics.median(error_counts), 0.5)
    return round(min(100.0, max(0.0, (max(error_counts) - baseline) / math.sqrt(baseline))), 3)


def compute_features(
    lines: Sequence[FeatureInput],
    *,
    system: str,
    novel_template_ids: set[str],
    catalog: ServiceCatalog | None = None,
) -> WindowFeatures:
    catalog = catalog or load_catalog()
    lexicon = load_lexicon()
    n = len(lines)
    levels = Counter(line.level or "UNKNOWN" for line in lines)
    errors = [line for line in lines if line.level in ERROR_LEVELS]
    times = sorted(line.ts for line in lines if line.ts is not None)
    error_times = sorted(line.ts for line in errors if line.ts is not None)
    start, end = (times[0], times[-1]) if times else (None, None)
    duration = (end - start).total_seconds() if start and end else 0.0

    if start and end and error_times:
        series = per_minute_counts(error_times, start, end)
        burst, peak = burst_score(series), float(max(series))
    else:
        burst, peak = 0.0, float(len(errors) > 0)

    lowered = [line.message.lower() for line in lines]
    keyword_hits = {
        name: sum(1 for text in lowered if pattern.search(text))
        for name, pattern in lexicon.items()
    }
    nodes = {line.node for line in lines if line.node}
    error_nodes = {line.node for line in errors if line.node}
    components = sorted({line.component for line in lines if line.component})
    error_components = {line.component for line in errors if line.component}
    criticality = {c: catalog.criticality(system, c) for c in error_components}
    error_templates = {line.template_id for line in errors}

    return WindowFeatures(
        n_events=n,
        n_templates=len({line.template_id for line in lines}),
        duration_s=round(duration, 3),
        events_per_min=round(n / max(duration / 60, 1.0), 3),
        level_counts=dict(levels),
        error_events=len(errors),
        error_ratio=round(len(errors) / n, 4) if n else 0.0,
        keyword_hits={k: v for k, v in keyword_hits.items() if v},
        burst_score=burst,
        peak_errors_per_min=peak,
        distinct_nodes=len(nodes),
        error_nodes=len(error_nodes),
        node_spread=round(len(error_nodes) / len(nodes), 4) if nodes else 0.0,
        novel_templates=len({line.template_id for line in lines} & novel_template_ids),
        novel_error_templates=len(error_templates & novel_template_ids),
        components=components[:50],
        critical_components=sorted(c for c, v in criticality.items() if v >= CRITICAL_COMPONENT)[
            :20
        ],
        max_component_criticality=max(criticality.values(), default=0.0) if errors else 0.0,
        persistence_s=round((error_times[-1] - error_times[0]).total_seconds(), 3)
        if len(error_times) > 1
        else 0.0,
    )
