"""Per-run budgets: tokens, cost, LLM calls, tool calls, steps and wall-clock time."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from aria.config import BudgetConfig
from aria.contracts.run import BudgetUsage
from aria.llm.base import BudgetExceededError, Usage


class BudgetGuard:
    """Checks a run's spending before each LLM call and records it after.

    When a limit is reached the guard raises ``BudgetExceededError``; agents catch it and fall back to
    their deterministic path, so a run never fails just because it ran out of budget.
    """

    def __init__(self, limits: BudgetConfig, usage: BudgetUsage | None = None) -> None:
        self.limits = limits
        self.usage = usage.model_copy(deep=True) if usage else BudgetUsage()
        self.calls: list[dict[str, Any]] = []  # one entry per LLM call made through this guard

    def _exhaust(self, reason: str) -> BudgetExceededError:
        if reason not in self.usage.exhausted:
            self.usage.exhausted.append(reason)
        return BudgetExceededError(reason)

    def elapsed_s(self) -> float:
        return (datetime.now(UTC) - self.usage.started_at).total_seconds()

    def check_llm(self, estimated_tokens: int = 0) -> None:
        if self.usage.llm_calls >= self.limits.max_llm_calls:
            raise self._exhaust("llm_calls")
        if self.usage.tokens + estimated_tokens > self.limits.max_tokens:
            raise self._exhaust("tokens")
        if self.usage.cost_usd >= self.limits.max_cost_usd:
            raise self._exhaust("cost")
        if self.elapsed_s() >= self.limits.max_latency_s:
            raise self._exhaust("latency")

    def check_tool(self) -> None:
        if self.usage.tool_calls >= self.limits.max_tool_calls:
            raise self._exhaust("tool_calls")

    def check_step(self) -> None:
        if self.usage.steps >= self.limits.max_steps:
            raise self._exhaust("steps")

    def record_llm(
        self, usage: Usage, *, task: str = "", provider: str = "", model: str = ""
    ) -> None:
        self.calls.append(
            {
                "task": task,
                "provider": provider,
                "model": model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "latency_ms": usage.latency_ms,
                "estimated": usage.estimated,
                "cost_usd": usage.cost_usd,
            }
        )
        self.usage.llm_calls += 1
        self.usage.tokens_in += usage.input_tokens
        self.usage.tokens_out += usage.output_tokens
        if usage.cost_usd is None:
            self.usage.cost_known = False
        else:
            self.usage.cost_usd = round(self.usage.cost_usd + usage.cost_usd, 6)

    def record_failure(
        self, *, task: str, provider: str, model: str, latency_ms: float, error: str
    ) -> None:
        """A call that failed (timeout, provider error): it cost time but no tokens."""
        self.calls.append(
            {
                "task": task,
                "provider": provider,
                "model": model,
                "input_tokens": 0,
                "output_tokens": 0,
                "latency_ms": latency_ms,
                "estimated": False,
                "error": error[:300],
            }
        )

    def record_tool(self) -> None:
        self.usage.tool_calls += 1

    def record_step(self) -> None:
        self.usage.steps += 1

    def snapshot(self) -> BudgetUsage:
        return self.usage.model_copy(deep=True)
