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
    # Why the model stopped: "stop", or "length" when it ran out of max_tokens (its answer is cut
    # short). None when the provider did not say.
    finish_reason: str | None = None
    cached: bool = False  # answered from ARIA's response cache: no provider call
    # The provider's own id for this response, and the model that wrote it (which can differ
    # from the one asked for, after a provider-side fallback). None when the provider did not say.
    response_id: str | None = None
    response_model: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


LimitKind = Literal["minute", "day", "spend_cap", "no_credit", "overload"]


@dataclass(frozen=True, slots=True)
class RateLimit:
    """Which limit a provider's refusal (HTTP 429, or its kin) names.

    * ``minute``: a per-minute limit; it lifts after ``retry_after`` seconds.
    * ``day``: a daily quota; waiting the provider's retry delay does not help, so it lifts at the
      next daily reset.
    * ``spend_cap``: the account's spending cap is reached; it lifts when the cap does (``until``
      when the provider said), or when the owner raises it.
    * ``no_credit``: the account has no credit or quota left (OpenAI's ``insufficient_quota``).
    * ``overload``: the provider is busy (HTTP 503 or 529), not this account's limit.
    """

    kind: LimitKind
    detail: str
    retry_after: float | None = None  # seconds, when the provider said
    until: float | None = None  # epoch seconds, when the provider named the moment


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
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        timed_out: bool = False,
        retry_after: float | None = None,
        limit: RateLimit | None = None,
        refused: bool = False,
        resend: bool = False,
        usage: Usage | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.timed_out = timed_out  # slow, not broken: fail over now and avoid it for a while
        self.retry_after = retry_after  # seconds the provider asked callers to wait, if it said
        self.limit = limit  # the rate limit, quota or cap the provider named, if any
        # The model declined to answer (a refusal or a content filter): asking it again, or
        # asking it to repair its answer, would only repeat that.
        self.refused = refused
        # The provider rejected how the request asked for JSON and its client now asks another
        # way: the same request may be sent again (each send is admitted on its own).
        self.resend = resend
        # What the failed call still cost, when the provider answered: a declined reply or one
        # cut short is billed like any other.
        self.usage = usage


class ModelRefusalError(ProviderError):
    """The model declined: an explicit refusal, or a content filter that withheld its reply.

    Nothing it returned is used. The router hands the call to the next provider, as it does
    any other failure, and never asks the same model to repair the answer.
    """

    def __init__(self, message: str, *, reason: str, usage: Usage | None = None) -> None:
        super().__init__(message, refused=True, usage=usage)
        self.reason = reason  # the finish reason that said so: "refusal", "content_filter", ...


class OutputTruncatedError(ProviderError):
    """Structured output stopped before it was complete, at its token limit.

    Half a JSON object is never parsed, even when what arrived happens to parse. The router
    treats this like any other failure: once more with a larger budget, then the next provider
    and finally the caller's deterministic path.
    """

    def __init__(self, message: str, *, reason: str = "length", usage: Usage | None = None) -> None:
        super().__init__(message, usage=usage)
        self.reason = reason


# Finish reasons that mean the reply was withheld: Anthropic's "refusal", OpenAI's
# "content_filter" and "refusal", and Gemini's own, lower-cased.
REFUSAL_REASONS = frozenset(
    {
        "refusal",
        "content_filter",
        "safety",
        "prohibited_content",
        "recitation",
        "blocklist",
        "spii",
        "image_safety",
    }
)
# Finish reasons that mean the reply ran out of room: OpenAI's "length", Anthropic's
# "max_tokens" and "model_context_window_exceeded", and Gemini's "max_tokens".
_CUT_SHORT = frozenset({"length", "max_tokens", "model_context_window_exceeded"})
# A turn Anthropic paused part way (server tools, which ARIA never sends): incomplete too.
_INCOMPLETE = frozenset({"length", "pause_turn"})


def finish_reason(raw: object) -> str | None:
    """A provider's finish reason in ARIA's words: lower-cased, and "length" for every reason
    that means the reply ran out of room. None when the provider did not say."""
    if not raw:
        return None
    reason = str(raw).lower()
    return "length" if reason in _CUT_SHORT else reason


def check_stop(provider: str, usage: Usage, *, structured: bool, refusal: str = "") -> None:
    """Raise when a reply must not be used, whatever its text says.

    * A refusal (``refusal`` is the model's own words or category, or the finish reason is one
      of ``REFUSAL_REASONS``) raises ``ModelRefusalError``, for text and structured requests.
    * Structured output that stopped early (``finish_reason`` "length", or a paused turn) raises
      ``OutputTruncatedError``. Text cut short is still an answer; ``finish_reason`` says so.

    Every provider client calls this, and the router calls it again on whatever a client
    returns, so no client can hand back a refused or truncated structured answer.
    """
    reason = finish_reason(usage.finish_reason) or ""  # a client may pass the provider's word
    if refusal or reason in REFUSAL_REASONS:
        why = reason if reason in REFUSAL_REASONS else "refusal"
        usage.finish_reason = why  # however the reply ended, it was declined
        detail = refusal[:200] or f"finish reason {why}"
        msg = f"{provider}: the model declined the request ({detail})"
        raise ModelRefusalError(msg, reason=why, usage=usage)
    if structured and reason in _INCOMPLETE:
        msg = f"{provider}: the reply stopped before it was complete (finish reason {reason})"
        raise OutputTruncatedError(msg, reason=reason, usage=usage)


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
