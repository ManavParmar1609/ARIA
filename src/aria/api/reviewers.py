"""How each reviewer decides, from the reviews ARIA already keeps.

For every person: how many reports they reviewed, how often they approved one without editing
it, how often they set a level other than ARIA's, and the median time from a run pausing for
review to their decision. All of it comes from stored rows (``repository.review_decisions``), so
it covers the runs still kept: a retention purge takes its runs' reviews with them.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ReviewerStats:
    reviewer: str
    decisions: int = 0
    approved_as_is: int = 0  # approved without editing anything
    edited: int = 0  # edited, then approved
    rejected: int = 0
    level_changed: int = 0  # settled on a level other than ARIA's
    waits_s: list[float] = field(default_factory=list)  # pause for review to the decision

    @property
    def median_wait_s(self) -> float | None:
        return round(statistics.median(self.waits_s), 1) if self.waits_s else None


def wait_s(paused_at: datetime | None, decided_at: datetime | None) -> float | None:
    """Seconds from the run pausing for review to the decision, when both are known. Clocks on
    two processes can disagree by a little, so a decision never reads as earlier than its pause."""
    if paused_at is None or decided_at is None:
        return None
    return max(0.0, (decided_at - paused_at).total_seconds())


def reviewer_stats(decisions: Iterable[Mapping[str, Any]]) -> list[ReviewerStats]:
    """Each reviewer's figures, the busiest reviewer first."""
    by_reviewer: dict[str, ReviewerStats] = {}
    for row in decisions:
        name = str(row["reviewer"])
        stats = by_reviewer.setdefault(name, ReviewerStats(name))
        stats.decisions += 1
        decision = row.get("decision")
        if decision == "approve":
            stats.approved_as_is += 1
        elif decision == "edit":
            stats.edited += 1
        elif decision == "reject":
            stats.rejected += 1
        aria, final = row.get("aria_level"), row.get("final_level")
        if aria and final and aria != final:
            stats.level_changed += 1
        waited = wait_s(row.get("paused_at"), row.get("decided_at"))
        if waited is not None:
            stats.waits_s.append(waited)
    return sorted(by_reviewer.values(), key=lambda s: (-s.decisions, s.reviewer.casefold()))
