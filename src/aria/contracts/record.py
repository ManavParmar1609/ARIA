"""The decision record: one entry per decision ARIA or a person took, hash-chained in order."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from aria.contracts.base import Contract, JsonDict

# What a decision was. The kinds a person sees in a run's record come first.
RecordKind = Literal[
    "review",  # a reviewer approved, edited or rejected a report
    "edit",  # what an edit changed
    "publish",  # a report was published
    "send",  # an approved message went out (or failed to)
    "blind_check",  # a person rated an incident without seeing ARIA's level
    "recalibration",  # a recalibration wrote a new severity model
    "model_swap",  # a running engine started using a different model version
    "purge",  # the retention purge removed runs
    "delete",  # a person deleted a run
]

# The hash the first entry chains to, so an empty record verifies and the first entry is checked
# like every other.
GENESIS = "0" * 64


class DecisionRecord(Contract):
    """One entry. Its hash covers every other field and the previous entry's hash."""

    seq: int = Field(ge=0)
    ts: datetime
    kind: RecordKind
    run_id: str | None = None
    # A reviewer's display name, "cli" for the operator at the command line, or "system".
    actor: str
    payload: JsonDict = Field(default_factory=dict)
    prev_hash: str = Field(min_length=64, max_length=64)
    hash: str = Field(min_length=64, max_length=64)


class ChainCheck(Contract):
    """Whether the record holds together, from the first entry to the last."""

    ok: bool
    length: int = Field(ge=0)
    # The first entry whose hash does not match its fields or the entry before it.
    first_broken: int | None = None
    # Why that entry breaks the chain, in a sentence.
    problem: str | None = None
    # The newest entry's hash: anchor it outside the database to catch a rewritten chain.
    head_hash: str | None = None
    checked_at: datetime
