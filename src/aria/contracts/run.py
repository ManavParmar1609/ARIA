"""Run-level state: plan, budgets, status and streamed events."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from aria.contracts.base import Contract, JsonDict, utcnow


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    PUBLISHED = "published"
    REJECTED = "rejected"
    FAILED = "failed"

    @property
    def terminal(self) -> bool:
        return self in (RunStatus.PUBLISHED, RunStatus.REJECTED, RunStatus.FAILED)


class Plan(Contract):
    """What the supervisor decided to do. Replanning rewrites this between attempts."""

    investigate: bool = True
    use_llm: bool = True
    fanout_shards: int = Field(default=1, ge=1, le=32)
    retrieval_k: int = Field(default=3, ge=1)
    retrieval_candidates: int = Field(default=12, ge=1)
    widen_level: int = Field(default=0, ge=0, le=3)
    context_lines: int = Field(default=120, ge=10, le=2_000)
    validation: Literal["standard", "strict"] = "standard"
    replans: int = Field(default=0, ge=0)
    max_replans: int = Field(default=2, ge=0)
    notes: list[str] = Field(default_factory=list)


class BudgetUsage(Contract):
    tokens_in: int = Field(default=0, ge=0)
    tokens_out: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)
    cost_known: bool = True
    llm_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    steps: int = Field(default=0, ge=0)
    started_at: datetime = Field(default_factory=utcnow)
    exhausted: list[str] = Field(default_factory=list)

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out


EventKind = Literal[
    "run_started",
    "node_started",
    "node_finished",
    "token",
    "tool_call",
    "llm_call",
    "replan",
    "budget",
    "guardrail",
    "interrupt",
    "review",
    "action",
    "run_finished",
    "checkpoint",
    "error",
]


class RunEvent(Contract):
    seq: int = Field(ge=0)
    run_id: str
    ts: datetime = Field(default_factory=utcnow)
    kind: EventKind
    node: str | None = None
    payload: JsonDict = Field(default_factory=dict)
