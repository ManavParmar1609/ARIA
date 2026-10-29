"""Types shared by every provider."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from aria.config import ProviderKind

Role = Literal["system", "user", "assistant"]
TokenCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    estimated: bool = False
    latency_ms: float = 0.0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(slots=True)
class LLMResult[T]:
    value: T
    text: str
    provider: str
    model: str
    usage: Usage
    attempts: list[dict[str, Any]] = field(default_factory=list)


class LLMError(RuntimeError):
    pass


class ProviderError(LLMError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class StructuredOutputError(LLMError):
    """Every provider in the chain answered, but none produced valid output."""

    def __init__(self, message: str, *, attempts: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []


class BudgetExceededError(LLMError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"budget exhausted: {reason}")
        self.reason = reason


class NoProviderAvailableError(LLMError):
    """No provider in the chain is enabled, healthy and reachable."""

    def __init__(self, message: str, *, attempts: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []


class ChatProvider(Protocol):
    name: str
    kind: ProviderKind
    model: str

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        json_schema: dict[str, Any] | None,
        schema_name: str,
        temperature: float,
        max_tokens: int,
        on_token: TokenCallback | None,
    ) -> tuple[str, Usage]: ...


class EmbeddingProvider(Protocol):
    name: str
    model: str

    async def embed(
        self, texts: Sequence[str], *, input_type: Literal["query", "passage"]
    ) -> list[list[float]]: ...


class RerankProvider(Protocol):
    name: str
    model: str

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]: ...


def estimate_tokens(text: str) -> int:
    """Rough token count (about four characters per token) when a provider reports no usage."""
    return max(1, len(text) // 4)
