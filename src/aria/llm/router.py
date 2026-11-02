"""Role-based routing over provider fallback chains.

Each role (adjudicator, investigator, reporter, ...) has an ordered chain of providers in
``config/aria.yaml``. The router skips providers that are disabled (no key or endpoint) or whose
circuit breaker is open, checks the run budget before every call, validates structured output
against its Pydantic schema plus a caller-supplied check, gives the model one repair attempt
with the validation errors, and only then falls back to the next provider. When the chain is
exhausted it raises ``NoProviderAvailableError`` and the caller takes its deterministic path.

Around every request to a provider:

* **Admission.** The quota ledger (aria.llm.quota) counts the request against the provider's
  limits before it goes. A provider with no room is skipped, and the skip is recorded as an
  attempt with its reason; one whose minute frees up within ``llm.quota.max_wait_s`` is waited
  for. Tokens are estimated from the messages and the reply budget, then replaced by what the
  provider reports.
* **Refusals for a limit.** A classified 429 (aria.llm.ratelimit) rests the provider in the
  ledger, which a restart remembers, and opens its breaker: a per-minute limit for the delay it
  names, a daily quota until the next reset (midnight Pacific), a spending cap or an empty
  account until then too, logged plainly.
* **One retry layer.** Clients send each request once. A failure hands the call to the next
  provider in the chain: that fallback is ARIA's only retry for provider calls, so one failure
  never multiplies into several requests against the same limit. The graph's node retry policy
  retries database and tool-server connection errors, never a provider call: the router turns
  every provider failure into a fallback before it can reach a node.
* **Stops.** A refusal or content filter raises ``ModelRefusalError``, and structured output
  cut short by ``max_tokens`` raises ``OutputTruncatedError``: the clients raise them, and the
  router checks every reply again, so neither is ever parsed. Both are failures like any other
  and end at the next provider or the caller's deterministic path. A refusal is never repaired
  on the same provider; a cut is asked for once more with twice the budget, never repaired.
  Neither rests the provider, and the tokens either was billed are counted. Text cut short is
  still an answer, marked ``finish_reason == "length"``.
* **The response cache** answers repeats of a deterministic request (temperature 0) to a real
  model from memory, so they spend none of its limits.

A view made by ``with_key`` (a visitor's own key) keeps all of this to itself: the visitor's
requests spend the visitor's limits, not this server's, never touch the ledger or the cache, and
their failures rest only the view's own breakers.
"""

from __future__ import annotations

import asyncio
import copy
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal, TypeVar

import httpx
import httpx2
from opentelemetry.trace import Span
from pydantic import BaseModel, SecretStr, ValidationError

from aria.config import (
    Environment,
    LLMConfig,
    ProviderConfig,
    ProviderKind,
    get_app_config,
    get_settings,
    register_reset_hook,
)
from aria.llm.base import (
    LLMResult,
    Message,
    NoProviderAvailableError,
    OutputTruncatedError,
    ProviderError,
    RateLimit,
    StructuredOutputError,
    TokenCallback,
    Usage,
    check_stop,
    estimate_tokens,
)
from aria.llm.budget import BudgetGuard
from aria.llm.cache import ResponseCache, cache_key
from aria.llm.claude import ClaudeProvider
from aria.llm.fake import FakeProvider
from aria.llm.jsonschema import extract_json, strict_schema
from aria.llm.local_embed import LocalEmbeddingProvider
from aria.llm.openai_compat import OpenAICompatibleProvider
from aria.llm.prompts import datamark_messages, repair_message
from aria.llm.quota import (
    Capacity,
    QuotaLedger,
    Refusal,
    Reservation,
    Ticket,
    Unreserved,
    request_tokens,
)
from aria.llm.visitor import VisitorKey
from aria.observability.logging import get_logger
from aria.observability.tracing import (
    error_type,
    genai_provider_name,
    genai_span,
    mark_error,
    record_metrics,
    record_response,
    server_attributes,
)

M = TypeVar("M", bound=BaseModel)
Validator = Callable[[Any], list[str]]
log = get_logger(__name__)

MAX_RESENDS = 3  # schema step-downs for one call: json_schema, guided_json, json_object, prompt
LONGER_REPLY_CAP = 8_000  # the larger budget a structured answer cut short gets, at most
_PACING_WAITS = 4  # how often one request waits for a minute window before it moves on
_UNTIL_RESET = frozenset({"day", "spend_cap", "no_credit"})


@dataclass
class CircuitBreaker:
    """Opens after ``threshold`` consecutive failures and lets one trial through after ``cooldown_s``.

    A timeout trips it at once and for longer (``trip_cooldown_s``): a provider that is slow now
    tends to stay slow, and every retry costs the run a full stall timeout. A provider that says
    how long to wait (a rate limit or quota with Retry-After) is left alone for that long, up to
    ``max_wait_s``, so calls stop spending its limit on refusals.
    """

    threshold: int = 3
    cooldown_s: float = 30.0
    trip_cooldown_s: float = 300.0
    max_wait_s: float = 3600.0
    clock: Callable[[], float] = time.monotonic
    failures: int = 0
    opened_at: float | None = None
    open_for: float = 0.0
    last_error: str | None = None

    @property
    def state(self) -> Literal["closed", "open", "half_open"]:
        if self.opened_at is None:
            return "closed"
        return "half_open" if self.clock() - self.opened_at >= self.open_for else "open"

    def allow(self) -> bool:
        return self.state != "open"

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self.last_error = None

    def failure(self, error: str, *, trip: bool = False, retry_after: float | None = None) -> None:
        """Count a failure; ``trip`` opens the circuit at once (a timeout: the provider is slow),
        and ``retry_after`` opens it for as long as the provider asked."""
        self.failures += 1
        self.last_error = error[:300]
        if retry_after is not None and retry_after > 0:
            self.opened_at, self.open_for = self.clock(), min(retry_after, self.max_wait_s)
        elif trip:
            self.opened_at, self.open_for = self.clock(), self.trip_cooldown_s
        elif self.failures >= self.threshold or self.state == "half_open":
            self.opened_at, self.open_for = self.clock(), self.cooldown_s


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


@dataclass(frozen=True)
class PoolCapacity:
    """The shared models' room now: per provider, and for whole model-written runs."""

    providers: list[Capacity]
    next_reset: float
    runs_left: int | None  # None: no daily limit bounds them
    back_at: float | None  # None: one more run fits now


@dataclass
class _Reply:
    """One provider call as the router saw it."""

    text: str = ""
    usage: Usage | None = None  # None: the call failed or was never sent
    error: ProviderError | None = None
    skipped: Refusal | None = None  # not sent: the provider had no room for it
    latency_ms: float = 0.0  # of a failed call

    @property
    def spent(self) -> Usage | None:
        """What the call cost: the answer's usage, or what a declined reply or one cut short
        still billed. None for a call that failed before the provider answered."""
        if self.usage is not None:
            return self.usage
        return self.error.usage if self.error is not None else None


@dataclass(frozen=True)
class _Observed:
    """One model call as telemetry sees it: the GenAI span attributes and client histograms
    (aria.observability.tracing), with identifiers and counts only."""

    provider: str  # gen_ai.provider.name
    requested: str  # gen_ai.request.model
    server: dict[str, Any]  # server.address and server.port

    def record(
        self, span: Span, usage: Usage | None, started: float, *, error: str | None = None
    ) -> None:
        """What the provider reported about its reply (none when it never answered), on the
        span and the histograms. Counts ARIA estimated go on the span, marked so, but never on
        the token histogram."""
        reported = usage is not None and not usage.estimated
        answered = usage.response_model if usage is not None else None
        response_model = answered or (self.requested if error is None else None)
        record_response(
            span,
            response_model=response_model,
            response_id=usage.response_id if usage is not None else None,
            finish_reasons=[usage.finish_reason] if usage and usage.finish_reason else [],
            input_tokens=usage.input_tokens if usage is not None else None,
            output_tokens=usage.output_tokens if usage is not None else None,
            estimated=usage is not None and usage.estimated,
        )
        record_metrics(
            operation="chat",
            provider=self.provider,
            request_model=self.requested,
            response_model=response_model,
            duration_s=time.perf_counter() - started,
            input_tokens=usage.input_tokens if usage is not None and reported else None,
            output_tokens=usage.output_tokens if usage is not None and reported else None,
            error=error,
            server=self.server,
        )


def _validation_errors(exc: Exception) -> list[str]:
    if isinstance(exc, ValidationError):
        return [
            f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
            for err in exc.errors(include_url=False)
        ][:10]
    return [f"output is not valid JSON: {exc}"]


def _when(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(epoch))


def _ms_since(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


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
        ledger: QuotaLedger | None = None,
        cache: ResponseCache | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        datamark: bool = False,
    ) -> None:
        self.config = config
        self.allow_fake = env is not Environment.PROD
        # Spotlighting by datamarking (guardrails.datamark_untrusted): every prompt's untrusted
        # blocks are marked on the way out, once, here, for every provider alike.
        self.datamark = datamark
        self._providers: dict[str, Any] = dict(providers or {})
        self._models_dir = models_dir
        self._breakers: dict[str, CircuitBreaker] = {}
        self._clock = clock
        self._breaker_args = (breaker_threshold, breaker_cooldown_s)
        self.ledger = ledger if ledger is not None else QuotaLedger.from_config(config)
        self.cache = cache if cache is not None else ResponseCache.from_config(config.cache)
        self._sleep = sleep
        # Set only on a view made by for_run: the day's requests set aside for one run.
        self._reservation: Reservation | None = None
        # Set only on a view made by with_key: a visitor's key, the providers it stands in for,
        # and the clients and breakers the view made for them.
        self._key: SecretStr | None = None
        self._keyed: tuple[str, ...] = ()
        self._own: dict[str, Any] = {}
        self._own_breakers: dict[str, CircuitBreaker] = {}

    # --- providers -----------------------------------------------------------------------------

    def breaker(self, name: str) -> CircuitBreaker:
        breakers = self._own_breakers if name in self._keyed else self._breakers
        if name not in breakers:
            threshold, cooldown = self._breaker_args
            breakers[name] = CircuitBreaker(
                threshold=threshold, cooldown_s=cooldown, clock=self._clock
            )
        return breakers[name]

    def is_set_up(self, name: str) -> bool:
        """Known, with its endpoint and credential, and allowed here (the offline stand-in only
        where it may answer), whether or not its breaker has it resting for now."""
        if name in self._keyed:
            return True  # the visitor's key is its credential
        cfg = self.config.providers.get(name)
        if name in self._providers:
            injected_kind = getattr(self._providers[name], "kind", None)
            fake = injected_kind is ProviderKind.FAKE
        elif cfg is None or not cfg.is_enabled():
            return False
        else:
            fake = cfg.kind is ProviderKind.FAKE
        return not fake or self.allow_fake

    def can_chat(self, name: str) -> bool:
        """Set up, and with a chat model to answer a run's steps with (the offline embedder, for
        one, only embeds)."""
        if not self.is_set_up(name):
            return False
        if name in self._providers:
            return callable(getattr(self._providers[name], "chat", None))
        cfg = self.config.providers[name]
        return cfg.kind is ProviderKind.FAKE or bool(cfg.chat_model)

    def is_available(self, name: str) -> bool:
        return self.is_set_up(name) and self.breaker(name).allow()

    def _is_model(self, name: str) -> bool:
        """A real model, not the offline stand-in or embedder, without making its client."""
        if name in self._providers:
            kind = getattr(self._providers[name], "kind", None)
        else:
            cfg = self.config.providers.get(name)
            kind = cfg.kind if cfg is not None else None
        return kind not in (ProviderKind.FAKE, ProviderKind.LOCAL, None)

    def provider(self, name: str) -> Any:
        if name in self._keyed:
            if name not in self._own:
                self._own[name] = _remote(name, self.config.providers[name], self._key)
            return self._own[name]
        if name not in self._providers:
            cfg = self.config.providers[name]
            if cfg.kind is ProviderKind.FAKE:
                self._providers[name] = FakeProvider(name)
            elif cfg.kind is ProviderKind.LOCAL:
                path = (self._models_dir / "embed_local.npz") if self._models_dir else None
                self._providers[name] = LocalEmbeddingProvider(name, model_path=path)
            else:
                self._providers[name] = _remote(name, cfg, None)
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

    def without(self, name: str | None) -> LLMRouter:
        """A view whose chains leave ``name`` out, for a check that should not run on the
        provider whose work it checks (the report critic). Providers, breakers, the ledger and
        the cache are shared; a role left with no chain falls back as configured."""
        if not name:
            return self
        routing = {
            role: [n for n in chain if n != name] for role, chain in self.config.routing.items()
        }
        view = copy.copy(self)
        view.config = self.config.model_copy(update={"routing": routing})
        return view

    def with_key(self, visitor: VisitorKey) -> LLMRouter:
        """A view in which a visitor's own key stands in for this server's key in the providers
        ``visitor_keys`` lists for its kind, which then lead every chain they are in, in that
        chain's own order.

        The view makes its own clients and circuit breakers for those providers, so the key
        answers only the work the view was made for, and its failures never rest or label this
        server's providers. Close the view with ``aclose``: it closes only what it made.
        """
        names = tuple(self.config.visitor_keys.providers.get(visitor.provider, ()))
        routing = {
            role: [*(n for n in chain if n in names), *(n for n in chain if n not in names)]
            for role, chain in self.config.routing.items()
        }
        view = copy.copy(self)
        view.config = self.config.model_copy(update={"routing": routing})
        view._key, view._keyed = visitor.key, names
        view._own, view._own_breakers = {}, {}
        view._reservation = None
        return view

    def for_run(self, reservation: Reservation | None) -> LLMRouter:
        """A view whose calls may use ``reservation``: the day's requests set aside for one
        run. Everything else is shared."""
        view = copy.copy(self)
        view._reservation = reservation
        return view

    def has_real_llm(self, role: str) -> bool:
        """True when a non-fake provider is available for the role."""
        return any(
            getattr(self.provider(name), "kind", None) is not ProviderKind.FAKE
            for name in self.chain(role)
        )

    # --- the shared models' limits -------------------------------------------------------------

    def run_chains(self, roles: Sequence[str]) -> dict[str, list[str]]:
        """For each role, the real models set up on this server's own keys that may take it, in
        order. Breakers are left out of it: a reservation is about the day's limits, not about
        whether a provider answered the last call."""
        return {
            role: [
                name
                for name in self.config.chain(role)
                if name not in self._keyed and self.is_set_up(name) and self._is_model(name)
            ]
            for role in roles
        }

    def reserve_run(self, needs: Mapping[str, int]) -> Reservation | Unreserved:
        """Set aside the day's requests for one run's calls (``needs``, by role)."""
        return self.ledger.reserve(needs, self.run_chains(list(needs)))

    def release_run(self, reservation: Reservation) -> int:
        return self.ledger.release(reservation)

    def run_back_at(self, needs: Mapping[str, int]) -> float | None:
        """None while one more run of ``needs`` fits in the shared models' limits, else when
        there may be room for it (epoch seconds)."""
        return self.ledger.check_run(needs, self.run_chains(list(needs)))

    def capacity(self, needs: Mapping[str, int]) -> PoolCapacity:
        chains = self.run_chains(list(needs))
        return PoolCapacity(
            providers=self.ledger.capacity(),
            next_reset=self.ledger.next_reset(),
            runs_left=self.ledger.runs_left(needs, chains),
            back_at=self.ledger.check_run(needs, chains),
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
        if self.datamark:
            messages = datamark_messages(messages)
        attempts: list[dict[str, Any]] = []
        total = Usage()
        chain = self.chain(role)
        longer = False  # the one retry with a larger budget, after an answer cut short
        for name in chain:
            provider = self.provider(name)
            conversation = list(messages)
            repair = 0
            while repair <= max_repairs:
                if attempts and on_reset is not None:
                    on_reset()
                if budget is not None:
                    budget.check_llm(sum(estimate_tokens(m.content) for m in conversation))
                reply = await self._call(
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
                if reply.usage is None:  # failed, declined, cut short or not sent
                    spent = reply.spent
                    if spent is not None:  # the provider answered, and billed the answer
                        total = _add(total, spent)
                        if budget is not None:
                            budget.record_llm(
                                spent,
                                task=task,
                                provider=name,
                                model=getattr(provider, "model", ""),
                            )
                    elif budget is not None and reply.error is not None:
                        budget.record_failure(
                            task=task,
                            provider=name,
                            model=getattr(provider, "model", ""),
                            latency_ms=float(attempts[-1].get("latency_ms", 0.0)),
                            error=str(attempts[-1].get("error", "")),
                        )
                    if isinstance(reply.error, OutputTruncatedError):
                        # Cut short: never parsed, and a repair would be cut short too. Ask
                        # once more with a larger budget; after a second cut, the next
                        # provider, which keeps the larger budget.
                        attempts[-1]["repair"] = repair
                        larger = min(max_tokens * 2, LONGER_REPLY_CAP)
                        if not longer and larger > max_tokens:
                            longer, max_tokens = True, larger
                            continue
                    break  # anything else: the next provider
                usage = reply.usage
                total = _add(total, usage)
                if budget is not None:
                    budget.record_llm(
                        usage, task=task, provider=name, model=getattr(provider, "model", "")
                    )
                try:
                    value = schema.model_validate(extract_json(reply.text))
                    errors = validator(value) if validator else []
                except (ValueError, ValidationError) as exc:
                    errors = _validation_errors(exc)
                if not errors:
                    done: dict[str, Any] = {"provider": name, "ok": True, "repair": repair}
                    if usage.cached:
                        done["cached"] = True
                    attempts.append(done)
                    return LLMResult(
                        value, reply.text, name, getattr(provider, "model", ""), total, attempts
                    )
                attempts.append(
                    {"provider": name, "ok": False, "repair": repair, "errors": errors[:5]}
                )
                log.info(
                    "llm.invalid_output", provider=name, task=task, repair=repair, errors=errors[:3]
                )
                conversation = [
                    *conversation,
                    Message("assistant", reply.text[:6_000]),
                    repair_message(errors),
                ]
                repair += 1
        if not chain or (attempts and all(a.get("skipped") for a in attempts)):
            msg = f"no provider is available for role {role!r}"
            if chain:
                msg += ": every provider is at its limit for now"
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
        if self.datamark:
            messages = datamark_messages(messages)
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
            reply = await self._call(
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
            if reply.usage is None:
                spent = reply.spent  # a declined reply is still billed
                if budget is not None and spent is not None:
                    budget.record_llm(
                        spent,
                        task=role,
                        provider=name,
                        model=str(model or getattr(provider, "model", "")),
                    )
                continue
            model_name = str(model or getattr(provider, "model", ""))
            if budget is not None:
                budget.record_llm(reply.usage, task=role, provider=name, model=model_name)
            if reply.usage.finish_reason == "length":
                # Text cut short is still an answer: no blind retry, but say so.
                log.info("llm.length_stop", provider=name, task=role, budget=max_tokens)
            attempts.append({"provider": name, "ok": True})
            return LLMResult(reply.text, reply.text, name, model_name, reply.usage, attempts)
        msg = f"no provider is available for role {role!r}"
        raise NoProviderAvailableError(msg, attempts=attempts)

    # --- one call ------------------------------------------------------------------------------

    async def _admit(self, name: str, tokens: int) -> Ticket | Refusal:
        """Count one request against ``name``'s limits, waiting for its minute window when room
        comes back within ``llm.quota.max_wait_s``; otherwise say why there is none."""
        deadline = self.ledger.now() + self.config.quota.max_wait_s
        for _ in range(_PACING_WAITS):
            outcome = self.ledger.acquire(name, tokens, reservation=self._reservation)
            if isinstance(outcome, Ticket):
                await self.ledger.persist()
                return outcome
            short = outcome.kind in ("minute", "tokens") and outcome.retry_at is not None
            if not short or outcome.retry_at is None or outcome.retry_at > deadline:
                return outcome
            await self._sleep(max(0.0, outcome.retry_at - self.ledger.now()))
        return self.ledger.acquire(name, tokens, reservation=self._reservation)

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
    ) -> _Reply:
        name = provider.name
        keyed = name in self._keyed  # a visitor's key: their limits, not this server's
        cfg = self.config.providers.get(name)
        key = None
        # The offline stand-in costs nothing and has no limits: only real models' answers are kept.
        real = getattr(provider, "kind", None) is not ProviderKind.FAKE
        if real and not keyed and temperature == 0 and self.cache.enabled:
            key = cache_key(
                provider=name,
                model=str(model or getattr(provider, "model", "")),
                endpoint=cfg.base_url if cfg else None,
                mode=str(getattr(provider, "mode", "")),
                messages=conversation,
                json_schema=json_schema,
                schema_name=task,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            hit = self.cache.get(key)
            if hit is not None:
                text, usage = hit
                if on_token is not None:
                    on_token(text)
                log.info("llm.cache_hit", provider=name, task=task)
                return _Reply(text, usage)
        for _ in range(MAX_RESENDS + 1):
            ticket: Ticket | None = None
            if not keyed:
                reply_budget = max_tokens + (cfg.reasoning_tokens if cfg else 0)
                outcome = await self._admit(
                    name, request_tokens(conversation, reply_budget, json_schema)
                )
                if isinstance(outcome, Refusal):
                    attempts.append(
                        {
                            "provider": name,
                            "ok": False,
                            "skipped": outcome.kind,
                            "error": f"{name}: no room: {outcome.reason}"[:300],
                        }
                    )
                    log.info("llm.quota_skip", provider=name, task=task, kind=outcome.kind)
                    return _Reply(skipped=outcome)
                ticket = outcome
            reply = await self._send(
                provider,
                conversation,
                role=role,
                task=task,
                json_schema=json_schema,
                temperature=temperature,
                max_tokens=max_tokens,
                on_token=on_token,
                model=model,
            )
            if ticket is not None:
                # What the provider reported replaces the estimate; without a report it stands.
                # A declined reply or one cut short is billed too, so its report counts.
                reported = reply.spent
                tokens = reported.total_tokens if reported and not reported.estimated else None
                self.ledger.settle(ticket, tokens=tokens)
            error = reply.error
            if error is not None and error.resend:
                continue  # the client now asks for JSON another way: send it again, admitted
            if error is not None:
                self._failed(name, error, keyed=keyed)
                record: dict[str, Any] = {
                    "provider": name,
                    "ok": False,
                    "error": str(error)[:300],
                    "status": error.status,
                    "latency_ms": reply.latency_ms,
                }
                if error.refused:
                    record["refused"] = True
                if isinstance(error, OutputTruncatedError):
                    record["stop"] = "length"
                if error.limit is not None:
                    record["limit"] = error.limit.kind
                attempts.append(record)
                return _Reply(error=error, latency_ms=reply.latency_ms)
            if (
                key is not None
                and reply.usage is not None
                and reply.usage.finish_reason != "length"
            ):
                self.cache.put(key, reply.text, reply.usage)
            return reply
        failed = ProviderError(f"{name}: rejected every way of asking for JSON")
        self._failed(name, failed, keyed=keyed)
        attempts.append({"provider": name, "ok": False, "error": str(failed), "latency_ms": 0.0})
        return _Reply(error=failed)

    async def _send(
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
        model: str | None,
    ) -> _Reply:
        """Send one request. Any failure comes back as a ProviderError, never raised: a client
        that lets a transport error through is caught here, so it never reaches a graph node's
        retry policy and multiplies into more requests.

        Each call is one GenAI client span and one record on the GenAI client histograms
        (aria.observability.tracing): identifiers, counts and finish reasons, never text."""
        breaker = self.breaker(provider.name)
        cfg = self.config.providers.get(provider.name)
        base_url = cfg.base_url if cfg is not None else None
        requested = str(model or provider.model)
        span_attrs = {
            "gen_ai.request.temperature": temperature,
            "gen_ai.request.max_tokens": max_tokens,
            "gen_ai.output.type": "json" if json_schema is not None else "text",
            "aria.role": role,
            "aria.task": task,
        }
        call = _Observed(
            provider=genai_provider_name(provider.kind, base_url),
            requested=requested,
            server=server_attributes(base_url),
        )
        with genai_span(
            "chat", kind=provider.kind, model=requested, base_url=base_url, attributes=span_attrs
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
                # The clients check how a reply ended; this checks again, so a client that
                # hands back a refusal, or JSON cut short, still never has it parsed.
                check_stop(provider.name, usage, structured=json_schema is not None)
            except (ProviderError, httpx.HTTPError, httpx2.HTTPError) as exc:
                # httpx's (the OpenAI-compatible client) and httpx2's (Anthropic's SDK)
                # transport errors, should a client let one through, become a fallback here.
                mark_error(span, exc)
                error = (
                    exc
                    if isinstance(exc, ProviderError)
                    else ProviderError(f"{provider.name}: {type(exc).__name__}", retryable=True)
                )
                # A declined reply or one cut short still says how it ended and what it cost.
                call.record(span, error.usage, started, error=error_type(exc))
                return _Reply(error=error, latency_ms=_ms_since(started))
            breaker.success()
            usage.latency_ms = usage.latency_ms or _ms_since(started)
            call.record(span, usage, started)
            return _Reply(text, usage)

    def _failed(self, name: str, error: ProviderError, *, keyed: bool) -> None:
        """Rest a provider after a failure: a limit in the ledger (this server's own keys) and
        the breaker; a refusal or a reply cut short nowhere (the model answered; the provider
        is fine)."""
        if error.refused:
            log.info("llm.declined", provider=name)
            return
        if isinstance(error, OutputTruncatedError):
            log.info("llm.length_stop", provider=name, reason=error.reason)
            return
        breaker = self.breaker(name)
        wait = error.retry_after
        limit = error.limit
        if limit is not None and not keyed:
            until = self.ledger.hold(name, limit)
            wait = max(0.0, until - self.ledger.now())
            self._report_limit(name, limit, until)
        elif limit is not None and limit.kind in _UNTIL_RESET:
            wait = breaker.max_wait_s  # a visitor's key: their view lives for one run
        breaker.failure(str(error), trip=error.timed_out, retry_after=wait)
        log.warning("llm.provider_error", provider=name, status=error.status)

    @staticmethod
    def _report_limit(name: str, limit: RateLimit, until: float) -> None:
        """Say plainly what happened and when the provider is tried again."""
        if limit.kind in ("minute", "overload"):
            log.info("llm.rate_limited", provider=name, limit=limit.kind, until=_when(until))
        elif limit.kind == "day":
            log.warning(
                "llm.daily_quota_used",
                provider=name,
                message=f"{name} has used its daily quota; ARIA will not call it again until "
                f"{_when(until)}, when the provider's day starts again.",
            )
        else:
            log.error(
                "llm.spend_cap",
                provider=name,
                message=f"{name} stopped answering: {limit.detail}. ARIA will not call it again "
                f"until {_when(until)}. Raise the cap or add credit with the provider; ARIA "
                "tries it again then.",
            )

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
                self.breaker(name).failure(str(exc), retry_after=exc.retry_after)
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
        """Close the clients this router made. A view with a visitor's key closes only its own:
        the rest belong to the router it was made from."""
        made = self._own if self._key is not None else self._providers
        for provider in list(made.values()):
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()
        if self._key is None:
            await self.ledger.persist()


def _remote(name: str, cfg: ProviderConfig, key: SecretStr | None) -> Any:
    """The client for a hosted provider: Claude's own, or the OpenAI-compatible one. ``key``
    replaces the key the config names (a visitor's)."""
    if cfg.kind is ProviderKind.ANTHROPIC:
        return ClaudeProvider(name, cfg, api_key=key)
    return OpenAICompatibleProvider(name, cfg, api_key=key)


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
        finish_reason=b.finish_reason,
        cached=a.cached and b.cached,
    )


@lru_cache(maxsize=1)
def get_router() -> LLMRouter:
    settings = get_settings()
    app = get_app_config()
    config = app.llm
    return LLMRouter(
        config,
        env=settings.env,
        models_dir=settings.models_dir,
        ledger=QuotaLedger.from_config(config, path=settings.quota_path),
        datamark=app.guardrails.datamark_untrusted,
    )


register_reset_hook(get_router.cache_clear)
