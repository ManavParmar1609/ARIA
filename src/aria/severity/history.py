"""What the database remembers about a system, read when one of its windows is triaged.

Two things, both read-only, and both absent when there is too little history:

* **The system's own baseline.** The median error ratio of the system's recent runs. A window's
  error ratio against it is a burn rate in the sense of the Google SRE workbook's alerting on
  SLOs (multiwindow, multi-burn-rate alerts): how many times faster than usual errors are
  arriving, which neither a count nor a bare ratio can say for a system that always logs some.
  It reaches the rules as ``error_ratio_vs_baseline`` (``aria.severity.rules.HISTORY_FEATURES``).
  Offline evaluations have no history, so there it changes nothing.
* **Patterns reviewers dismissed.** The log patterns (templates) on the issue lines of runs whose
  reviewers discarded the draft or lowered the level to SEV4. When most of a window's issue lines
  follow them, the reviewer is told how many times; the level itself never moves for it.

``SeverityEngine.assess`` reads both in a thread (``SystemHistory.lookup``). The runner gives the
engine its database; an engine built without one, as evaluations and tests build them, reads
nothing.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping
from dataclasses import dataclass, field

from sqlalchemy.engine import Engine

from aria.db import repository as repo
from aria.parsing.features import ISSUE_LEVELS

# Runs behind a baseline: the system's latest this many, and at least MIN_BASELINE_RUNS of them.
BASELINE_RUNS = 30
MIN_BASELINE_RUNS = 5
# A system whose windows usually log no errors at all still gets a baseline, one error in a
# thousand lines, so its first errors read as a burn rate rather than as infinity.
MIN_BASELINE_RATIO = 0.001
MAX_BURN = 1_000.0
# A window's issue lines follow a dismissed pattern when at least this share of them match.
DISMISSED_SHARE = 0.5
# Reviews read for the patterns: the newest this many on the system.
DISMISSED_REVIEWS = 200


@dataclass(frozen=True)
class DismissedMatch:
    """How a window's issue lines compare with the patterns reviewers dismissed before."""

    reviews: int  # dismissed reviews whose runs shared a matched pattern
    matched_lines: int
    issue_lines: int
    templates: tuple[str, ...]  # the matched template ids, most lines first


@dataclass(frozen=True)
class DismissedPatterns:
    """Log patterns on the issue lines of one system's runs whose reviews dismissed the rating."""

    runs_by_template: Mapping[str, frozenset[str]]  # template id -> the dismissed runs that had it
    reviews: int  # dismissed reviews whose lines are stored

    def match(self, issue_templates: Mapping[str, int], issue_lines: int) -> DismissedMatch | None:
        """The match when most of a window's issue lines follow dismissed patterns, else None."""
        matched = {t: n for t, n in issue_templates.items() if t in self.runs_by_template}
        lines = sum(matched.values())
        if not lines or lines < DISMISSED_SHARE * max(issue_lines, 1):
            return None
        runs = frozenset[str]().union(*(self.runs_by_template[t] for t in matched))
        return DismissedMatch(
            reviews=len(runs),
            matched_lines=lines,
            issue_lines=max(issue_lines, lines),
            templates=tuple(sorted(matched, key=lambda t: (-matched[t], t)))[:10],
        )


@dataclass(frozen=True)
class HistoryContext:
    """What the engine learned about a system before rating one of its windows."""

    features: dict[str, float] = field(default_factory=dict)  # HISTORY_FEATURES, or empty
    dismissed: DismissedPatterns | None = None


class SystemHistory:
    """Read queries over the runs and reviews a deployment has stored, per system."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def baseline(self, system: str) -> tuple[float, int] | None:
        """The median error ratio of the system's recent runs, and how many runs it rests on;
        None with fewer than ``MIN_BASELINE_RUNS``."""
        ratios = repo.recent_error_ratios(self.engine, system, limit=BASELINE_RUNS)
        if len(ratios) < MIN_BASELINE_RUNS:
            return None
        return statistics.median(ratios), len(ratios)

    def baseline_features(self, system: str, *, error_ratio: float) -> dict[str, float]:
        """The window's error ratio against the baseline, as rule features; empty without one."""
        found = self.baseline(system)
        if found is None:
            return {}
        median, runs = found
        burn = min(MAX_BURN, error_ratio / max(median, MIN_BASELINE_RATIO))
        return {
            "error_ratio_vs_baseline": round(burn, 3),
            "baseline_error_ratio": round(median, 4),
            "baseline_runs": float(runs),
        }

    def dismissed(self, system: str) -> DismissedPatterns | None:
        """The patterns on the issue lines of the system's dismissed runs; None without any."""
        runs = repo.dismissed_reviews(self.engine, system, limit=DISMISSED_REVIEWS)
        if not runs:
            return None
        templates = repo.issue_templates_of(self.engine, runs, levels=ISSUE_LEVELS)
        by_template: dict[str, set[str]] = {}
        for run_id, ids in templates.items():
            for template in ids:
                by_template.setdefault(template, set()).add(run_id)
        if not by_template:
            return None
        return DismissedPatterns(
            {t: frozenset(r) for t, r in by_template.items()}, reviews=len(templates)
        )

    def lookup(self, system: str, *, error_ratio: float) -> HistoryContext:
        return HistoryContext(
            self.baseline_features(system, error_ratio=error_ratio), self.dismissed(system)
        )
