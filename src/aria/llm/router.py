"""Role-based routing over provider fallback chains.

Each role (adjudicator, investigator, reporter, ...) has an ordered chain of providers in
``config/aria.yaml``. The router skips providers that are disabled (no key or endpoint) or whose
circuit breaker is open, checks the run budget before every call, validates structured output
against its Pydantic schema plus a caller-supplied check, gives the model one repair attempt
with the validation errors, and only then falls back to the next provider. When the chain is
exhausted it raises ``NoProviderAvailableError`` and the caller takes its deterministic path.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from aria.config import (
    Environment,
    LLMConfig,
    ProviderKind,
    get_app_config,
    get_settings,
    register_reset_hook,
)
from aria.llm.base import (
    LLMResult,
    Message,
    NoProviderAvailableError,
    ProviderError,
    StructuredOutputError,
    TokenCallback,
    Usage,
    estimate_tokens,
)
from aria.llm.budget import BudgetGuard
from aria.llm.fake import FakeProvider
from aria.llm.jsonschema import extract_json, strict_schema
from aria.llm.local_embed import LocalEmbeddingProvider
from aria.llm.openai_compat import OpenAICompatibleProvider
from aria.llm.prompts import repair_message
from aria.observability.logging import get_logger
from aria.observability.tracing import capture_content, genai_span, mark_error

M = TypeVar("M", bound=BaseModel)
Validator = Callable[[Any], list[str]]
log = get_logger(__name__)


@dataclass
class CircuitBreaker:
    """Opens after ``threshold`` consecutive failures and lets one trial through after ``cooldown_s``."""

    threshold: int = 3
    cooldown_s: float = 30.0
    clock: Callable[[], float] = time.monotonic
    failures: int = 0
    opened_at: float | None = None
    last_error: str | None = None

    @property
    def state(self) -> Literal["closed", "open", "half_open"]:
        if self.opened_at is None:
            return "closed"
        return "half_open" if self.clock() - self.opened_at >= self.cooldown_s else "open"

    def allow(self) -> bool:
        return self.state != "open"

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self.last_error = None

    def failure(self, error: str) -> None:
        self.failures += 1
        self.last_error = error[:300]
        if self.failures >= self.threshold or self.state == "half_open":
            self.opened_at = self.clock()


@dataclass
class Embedder:
    """An embedding provider plus the identity of its vector space.

    ``model`` names the embedding model (not the provider's chat model), so stored vectors are
    reused only when they came from the same space.
    """

    name: str
    model: str
    provider: Any

    async def embed(
        self, texts: Sequence[str], *, input_type: Literal["query", "passage"] = "passage"
    ) -> list[list[float]]:
        vectors: list[list[float]] = await self.provider.embed(texts, input_type=input_type)
        return vectors


@dataclass
class ProviderStatus:
    name: str
    kind: str
    enabled: bool
    chat_model: str | None
    embedding_model: str | None
    verified: bool
    breaker: str
    last_error: str | None
    roles: list[str] = field(default_factory=list)


def _validation_errors(exc: Exception) -> list[str]:
    if isinstance(exc, ValidationError):
        return [
            f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
            for err in exc.errors(include_url=False)
        ][:10]
    return [f"output is not valid JSON: {exc}"]


class LLMRouter:
    def __init__(
        self,
        config: LLMConfig,
        *,
        env: Environment = Environment.DEV,
        providers: Mapping[str, Any] | None = None,
        models_dir: Any = None,
        clock: Callable[[], float] = time.monotonic,
        breaker_threshold: int = 3,
        breaker_cooldown_s: float = 30.0,
    ) -> None:
        self.config = config
        self.allow_fake = env is not Environment.PROD
        self._providers: dict[str, Any] = dict(providers or {})
        self._models_dir = models_dir
        self._breakers: dict[str, CircuitBreaker] = {}
        self._clock = clock
        self._breaker_args = (breaker_threshold, breaker_cooldown_s)

    # --- providers -----------------------------------------------------------------------------

    def breaker(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            threshold, cooldown = self._breaker_args
            self._breakers[name] = CircuitBreaker(threshold, cooldown, self._clock)
        return self._breakers[name]

    def is_available(self, name: str) -> bool:
        cfg = self.config.providers.get(name)
        if name in self._providers:
            injected_kind = getattr(self._providers[name], "kind", None)
            fake = injected_kind is ProviderKind.FAKE
        elif cfg is None or not cfg.is_enabled():
            return False
        else:
            fake = cfg.kind is ProviderKind.FAKE
        if fake and not self.allow_fake:
            return False
        return self.breaker(name).allow()

    def provider(self, name: str) -> Any:
        if name not in self._providers:
            cfg = self.config.providers[name]
            if cfg.kind is ProviderKind.FAKE:
                self._providers[name] = FakeProvider(name)
            elif cfg.kind is ProviderKind.LOCAL:
                path = (self._models_dir / "embed_local.npz") if self._models_dir else None
                self._providers[name] = LocalEmbeddingProvider(name, model_path=path)
            else:
                self._providers[name] = OpenAICompatibleProvider(name, cfg)
        return self._providers[name]

    def chain(self, role: str) -> list[str]:
        return [name for name in self.config.chain(role) if self.is_available(name)]

    def prefer(self, name: str | None) -> LLMRouter:
        """A view that tries ``name`` first for every role; providers and breakers are shared.

        Roles keep their own fallbacks after it. The fake provider is never added to a chain that
        leaves it out on purpose (the adjudicator's).
        """
        if not name or name not in self.config.providers:
            return self
        routing = {
            role: [name, *(n for n in chain if n != name)]
            if name != "fake" or "fake" in chain
            else list(chain)
            for role, chain in self.config.routing.items()
        }
        view = copy.copy(self)
        view.config = self.config.model_copy(update={"routing": routing})
        return view

    def has_real_llm(self, role: str) -> bool:
        """True when a non-fake provider is available for the role."""
        return any(
            getattr(self.provider(name), "kind", None) is not ProviderKind.FAKE
            for name in self.chain(role)
        )

    # --- structured chat -----------------------------------------------------------------------

    async def structured(
        self,
        role: str,
        task: str,
        messages: Sequence[Message],
        schema: type[M],
        *,
        json_schema: dict[str, Any] | None = None,
        validator: Validator | None = None,
        budget: BudgetGuard | None = None,
        on_token: TokenCallback | None = None,
        on_reset: Callable[[], None] | None = None,
        temperature: float = 0.1,
        max_tokens: int = 1_500,
        max_repairs: int = 1,
    ) -> LLMResult[M]:
        schema_dict = json_schema or strict_schema(schema)
        attempts: list[dict[str, Any]] = []
        total = Usage()
        chain = self.chain(role)
        for name in chain:
            provider = self.provider(name)
            conversation = list(messages)
            for repair in range(max_repairs + 1):
                if attempts and on_reset is not None:
                    on_reset()
                if budget is not None:
                    budget.check_llm(sum(estimate_tokens(m.content) for m in conversation))
                text, usage = await self._call(
                    provider,
                    conversation,
                    role=role,
                    task=task,
                    json_schema=schema_dict,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    on_token=on_token,
                    attempts=attempts,
                )
                if usage is None:  # provider error: next provider
                    break
                total = _add(total, usage)
                if budget is not None:
                    budget.record_llm(usage)
                try:
                    value = schema.model_validate(extract_json(text))
                    errors = validator(value) if validator else []
                except (ValueError, ValidationError) as exc:
                    errors = _validation_errors(exc)
                if not errors:
                    attempts.append({"provider": name, "ok": True, "repair": repair})
                    return LLMResult(
                        value, text, name, getattr(provider, "model", ""), total, attempts
                    )
                attempts.append(
                    {"provider": name, "ok": False, "repair": repair, "errors": errors[:5]}
                )
                log.info(
                    "llm.invalid_output", provider=name, task=task, repair=repair, errors=errors[:3]
                )
                conversation = [
                    *conversation,
                    Message("assistant", text[:6_000]),
                    repair_message(errors),
                ]
        if not chain:
            msg = f"no provider is available for role {role!r}"
            raise NoProviderAvailableError(msg, attempts=attempts)
        msg = f"no provider produced valid {task} output"
        raise StructuredOutputError(msg, attempts=attempts)

    async def complete(
        self,
        role: str,
        messages: Sequence[Message],
        *,
        budget: BudgetGuard | None = None,
        on_token: TokenCallback | None = None,
        temperature: float = 0.2,
        max_tokens: int = 800,
        model_field: Literal["chat_model", "safety_model"] = "chat_model",
        chain: Sequence[str] | None = None,
    ) -> LLMResult[str]:
        attempts: list[dict[str, Any]] = []
        names = (
            [n for n in chain if self.is_available(n)] if chain is not None else self.chain(role)
        )
        for name in names:
            provider = self.provider(name)
            cfg = self.config.providers.get(name)
            model = getattr(cfg, model_field, None) if cfg else None
            if budget is not None:
                budget.check_llm(sum(estimate_tokens(m.content) for m in messages))
            text, usage = await self._call(
                provider,
                list(messages),
                role=role,
                task="text",
                json_schema=None,
                temperature=temperature,
                max_tokens=max_tokens,
                on_token=on_token,
                attempts=attempts,
                model=model if model_field != "chat_model" else None,
            )
            if usage is None:
                continue
            if budget is not None:
                budget.record_llm(usage)
            attempts.append({"provider": name, "ok": True})
            model_name = str(model or getattr(provider, "model", ""))
            return LLMResult(text, text, name, model_name, usage, attempts)
        msg = f"no provider is available for role {role!r}"
        raise NoProviderAvailableError(msg, attempts=attempts)

    async def _call(
        self,
        provider: Any,
        conversation: list[Message],
        *,
        role: str,
        task: str,
        json_schema: dict[str, Any] | None,
        temperature: float,
        max_tokens: int,
        on_token: TokenCallback | None,
        attempts: list[dict[str, Any]],
        model: str | None = None,
    ) -> tuple[str, Usage | None]:
        name = provider.name
        breaker = self.breaker(name)
        span_attrs = {
            "gen_ai.request.temperature": temperature,
            "gen_ai.request.max_tokens": max_tokens,
            "aria.role": role,
            "aria.task": task,
        }
        with genai_span(
            "chat", kind=provider.kind, model=model or provider.model, attributes=span_attrs
        ) as span:
            started = time.perf_counter()
            try:
                kwargs: dict[str, Any] = {
                    "json_schema": json_schema,
                    "schema_name": task,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "on_token": on_token,
                }
                if model is not None:
                    kwargs["model"] = model
                text, usage = await provider.chat(conversation, **kwargs)
            except ProviderError as exc:
                breaker.failure(str(exc))
                mark_error(span, exc)
                attempts.append(
                    {"provider": name, "ok": False, "error": str(exc)[:300], "status": exc.status}
                )
                log.warning("llm.provider_error", provider=name, task=task, status=exc.status)
                return "", None
            breaker.success()
            usage.latency_ms = usage.latency_ms or round((time.perf_counter() - started) * 1000, 1)
            span.set_attribute("gen_ai.usage.input_tokens", usage.input_tokens)
            span.set_attribute("gen_ai.usage.output_tokens", usage.output_tokens)
            span.set_attribute("gen_ai.response.model", model or provider.model)
            if capture_content():
                span.set_attribute("gen_ai.output.text", text[:4_000])
            return text, usage

    # --- embeddings and reranking --------------------------------------------------------------

    def embedding_provider(self, name: str | None = None) -> Embedder | None:
        """The named embedding provider, or the first available one in the embeddings chain.

        Stored vectors carry the embedder's ``model`` id, so an index is never queried with
        vectors from a different model.
        """
        names = [name] if name else self.config.embeddings
        for candidate in names:
            cfg = self.config.providers.get(candidate)
            if cfg is None or not cfg.is_enabled() or not self.breaker(candidate).allow():
                continue
            if cfg.kind is ProviderKind.LOCAL:
                provider = self.provider(candidate)
                return Embedder(candidate, str(provider.model), provider)
            if cfg.embedding_model:
                return Embedder(
                    candidate, f"{candidate}/{cfg.embedding_model}", self.provider(candidate)
                )
        return None

    async def rerank(self, query: str, passages: Sequence[str]) -> tuple[str, list[float]] | None:
        for name in self.config.rerank:
            cfg = self.config.providers.get(name)
            if cfg is None or not cfg.is_enabled() or not (cfg.rerank_model and cfg.rerank_url):
                continue
            if not self.breaker(name).allow():
                continue
            provider = self.provider(name)
            try:
                scores = await provider.rerank(query, passages)
            except ProviderError as exc:
                self.breaker(name).failure(str(exc))
                continue
            self.breaker(name).success()
            return name, scores
        return None

    # --- status --------------------------------------------------------------------------------

    def status(self) -> list[ProviderStatus]:
        roles: dict[str, list[str]] = {}
        for role, chain in self.config.routing.items():
            for name in chain:
                roles.setdefault(name, []).append(role)
        for name in self.config.embeddings:
            roles.setdefault(name, []).append("embeddings")
        out = []
        for name, cfg in self.config.providers.items():
            breaker = self.breaker(name)
            enabled = cfg.is_enabled() and (cfg.kind is not ProviderKind.FAKE or self.allow_fake)
            out.append(
                ProviderStatus(
                    name=name,
                    kind=str(cfg.kind),
                    enabled=enabled,
                    chat_model=cfg.chat_model or None,
                    embedding_model=cfg.embedding_model or None,
                    verified=cfg.verified,
                    breaker=breaker.state,
                    last_error=breaker.last_error,
                    roles=roles.get(name, []),
                )
            )
        return out

    async def aclose(self) -> None:
        for provider in self._providers.values():
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()


def _add(a: Usage, b: Usage) -> Usage:
    cost = (
        None
        if a.cost_usd is None and b.cost_usd is None
        else (a.cost_usd or 0.0) + (b.cost_usd or 0.0)
    )
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cost_usd=cost,
        estimated=a.estimated or b.estimated,
        latency_ms=a.latency_ms + b.latency_ms,
    )


@lru_cache(maxsize=1)
def get_router() -> LLMRouter:
    settings = get_settings()
    return LLMRouter(get_app_config().llm, env=settings.env, models_dir=settings.models_dir)


register_reset_hook(get_router.cache_clear)
