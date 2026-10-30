"""Which parts of a parsed window point at the problem.

Errors (ERROR and FATAL lines) first; then warnings from templates the system's history has never
shown; then other warnings. Many incidents in the Loghub systems, HDFS and ZooKeeper among them,
only ever log at WARN, so an error-only view would miss them. The parser orders templates,
evidence and context lines this way, and retrieval, incident memory and the investigator aim at
the same signal.
"""

from __future__ import annotations

from aria.contracts.parsing import ParsedBatch, TemplateStat
from aria.parsing.features import ERROR_LEVELS, WARN

__all__ = [
    "WARN",
    "error_count",
    "is_signal",
    "line_rank",
    "signal_components",
    "signal_templates",
    "warning_count",
]


def error_count(template: TemplateStat) -> int:
    return sum(n for level, n in template.levels.items() if level in ERROR_LEVELS)


def warning_count(template: TemplateStat) -> int:
    return template.levels.get(WARN, 0)


def is_signal(template: TemplateStat, *, history: bool = True) -> bool:
    """An error template, or a warning the history has never shown. Without a history to judge
    novelty against (``history`` False), every warning counts."""
    return template.error_like or (warning_count(template) > 0 and (template.novel or not history))


def line_rank(level: str | None, *, novel: bool) -> int:
    """Lower is stronger: error, new warning, warning, other new line, anything else."""
    if level in ERROR_LEVELS:
        return 0
    if level == WARN:
        return 1 if novel else 2
    return 3 if novel else 4


def signal_templates(batch: ParsedBatch) -> list[TemplateStat]:
    """The window's signal templates, strongest first (the parser ranks ``batch.templates``)."""
    history = batch.template_history > 0
    return [t for t in batch.templates if is_signal(t, history=history)]


def signal_components(batch: ParsedBatch, limit: int = 6) -> list[str]:
    """Components carrying the signal, strongest first; critical components logging errors lead."""
    out = list(batch.features.critical_components)
    for template in signal_templates(batch):
        out += [c for c in template.components if c not in out]
    return out[:limit]
