"""The feature vector the log-severity model reads.

Counts are log-scaled so a window with 10,000 errors does not dominate one with 100; ratios and
criticality stay on their natural 0-1 scale. Rule probabilities are included, so the model
learns how far to trust each rule family instead of re-deriving them.
"""

from __future__ import annotations

import math

from aria.contracts.base import SEVERITY_ORDER
from aria.parsing.catalog import load_lexicon
from aria.severity.rules import FeatureSpace, RuleEvaluation

_LOG_COUNTS = (
    "n_events",
    "error_events",
    "events_per_min",
    "peak_errors_per_min",
    "distinct_nodes",
    "error_nodes",
    "n_templates",
    "novel_templates",
    "novel_error_templates",
    "n_critical_components",
    "alerts.firing",
    "alerts.critical",
    "alerts.warning",
)
_RAW = ("error_ratio", "node_spread", "max_component_criticality")


def log_feature_names() -> list[str]:
    names = [f"log1p.{name}" for name in _LOG_COUNTS]
    names += list(_RAW)
    names += ["burst_score", "persistence_min_log1p", "frac.WARN", "frac.ERROR", "frac.FATAL"]
    names += [f"log1p.keyword_hits.{c}" for c in load_lexicon()]
    names += [f"rule_p.{s}" for s in SEVERITY_ORDER]
    names += ["floor_rank"]
    return names


def log_feature_row(values: FeatureSpace, rules: RuleEvaluation) -> dict[str, float]:
    row: dict[str, float] = {
        f"log1p.{name}": math.log1p(max(0.0, values.get(name, 0.0))) for name in _LOG_COUNTS
    }
    for name in _RAW:
        row[name] = values.get(name, 0.0)
    n = max(1.0, values.get("n_events", 0.0))
    row["burst_score"] = min(values.get("burst_score", 0.0), 50.0) / 10.0
    row["persistence_min_log1p"] = math.log1p(values.get("persistence_s", 0.0) / 60.0)
    for level in ("WARN", "ERROR", "FATAL"):
        row[f"frac.{level}"] = values.get(f"level_counts.{level}", 0.0) / n
    for category in load_lexicon():
        row[f"log1p.keyword_hits.{category}"] = math.log1p(
            values.get(f"keyword_hits.{category}", 0.0)
        )
    for severity in SEVERITY_ORDER:
        row[f"rule_p.{severity}"] = rules.probabilities[severity]
    # 0 = SEV1 floor ... 3 = SEV4; 4 = no floor.
    row["floor_rank"] = float(rules.floor.rank if rules.floor is not None else len(SEVERITY_ORDER))
    return row
