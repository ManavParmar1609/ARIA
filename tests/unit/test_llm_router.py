"""Router behaviour: chains, fallback, circuit breaking, repair, budgets and streaming."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel

from aria.config import (
    BudgetConfig,
    Environment,
    LLMConfig,
    ProviderConfig,
    ProviderKind,
    get_app_config,
)
from aria.llm.base import (
    BudgetExceededError,
    Message,
    NoProviderAvailableError,
    ProviderError,
    StructuredOutputError,
    Usage,
)
from aria.llm.budget import BudgetGuard
from aria.llm.fake import FakeProvider
from aria.llm.local_embed import LocalEmbeddingProvider
from aria.llm.router import CircuitBreaker, LLMRouter, get_router


class Pick(BaseModel):
    choice: str


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class FailingProvider:
    kind = ProviderKind.NVIDIA_NIM
    model = "broken"

    def __init__(
        self, name: str = "nim", status: int = 503, retry_after: float | None = None
    ) -> None:
        self.name = name
        self.status = status
        self.retry_after = retry_after
        self.calls = 0

    async def chat(self, messages: Any, **kwargs: Any) -> tuple[str, Usage]:
        self.calls += 1
        raise ProviderError(
            f"{self.name}: HTTP {self.status}",
            status=self.status,
            retryable=True,
            retry_after=self.retry_after,
        )


def _config(**routing: list[str]) -> LLMConfig:
    return LLMConfig(
        providers={
            "nim": ProviderConfig(
                kind=ProviderKind.NVIDIA_NIM,
                base_url="http://nim/v1",
                allow_no_key=True,
                chat_model="m",
            ),
            "fake": ProviderConfig(kind=ProviderKind.FAKE),
        },
        routing=routing or {"default": ["nim", "fake"]},
    )


MESSAGES = [Message("user", "pick one")]


def test_default_config_routes_offline_to_fake_but_never_adjudicates_with_it() -> None:
    router = get_router()
    assert router.chain("reporter") == ["fake"]
    assert router.chain("adjudicator") == []
    assert not router.has_real_llm("reporter")
    assert get_router() is router  # cached until reset


def test_a_key_enables_the_hosted_nim_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    router = LLMRouter(get_app_config().llm)
    assert router.chain("adjudicator") == ["nim", "nim-fallback"]
    assert router.chain("reporter") == ["nim", "nim-fallback", "fake"]
    assert router.has_real_llm("reporter")


def test_gemini_is_tried_before_hosted_nim_when_both_keys_are_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-x")
    router = LLMRouter(get_app_config().llm)
    assert router.chain("adjudicator") == ["gemini", "gemini-lite", "nim", "nim-fallback"]
    assert router.chain("reporter") == ["gemini", "gemini-lite", "nim", "nim-fallback", "fake"]


def test_production_never_uses_the_fake_provider() -> None:
    router = LLMRouter(get_app_config().llm, env=Environment.PROD)
    assert router.chain("reporter") == []
    assert not next(s for s in router.status() if s.name == "fake").enabled


async def test_falls_back_to_next_provider_and_records_attempts() -> None:
    failing = FailingProvider()
    fake = FakeProvider(script={"pick": ['{"choice": "b"}']})
    router = LLMRouter(_config(), providers={"nim": failing, "fake": fake})
    result = await router.structured("default", "pick", MESSAGES, Pick)
    assert result.value.choice == "b"
    assert result.provider == "fake"
    assert result.attempts[0]["provider"] == "nim"
    assert result.attempts[0]["ok"] is False
    assert result.attempts[-1] == {"provider": "fake", "ok": True, "repair": 0}


async def test_circuit_breaker_opens_then_half_opens() -> None:
    clock = Clock()
    failing = FailingProvider()
    fake = FakeProvider(script={"pick": ['{"choice": "a"}'] * 5})
    router = LLMRouter(
        _config(),
        providers={"nim": failing, "fake": fake},
        clock=clock,
        breaker_threshold=2,
        breaker_cooldown_s=10,
    )
    for _ in range(2):
        await router.structured("default", "pick", MESSAGES, Pick)
    assert router.breaker("nim").state == "open"
    assert router.chain("default") == ["fake"]
    await router.structured("default", "pick", MESSAGES, Pick)
    assert failing.calls == 2  # skipped while open
    clock.now = 11
    assert router.breaker("nim").state == "half_open"
    await router.structured("default", "pick", MESSAGES, Pick)
    assert failing.calls == 3
    assert router.breaker("nim").state == "open"  # the trial failed, so it re-opens


async def test_a_provider_that_says_when_to_come_back_is_skipped_until_then() -> None:
    clock = Clock()
    limited = FailingProvider(status=429, retry_after=90)
    fake = FakeProvider(script={"pick": ['{"choice": "a"}'] * 5})
    router = LLMRouter(
        _config(), providers={"nim": limited, "fake": fake}, clock=clock, breaker_threshold=3
    )
    await router.structured("default", "pick", MESSAGES, Pick)
    assert router.breaker("nim").state == "open"  # one refusal is enough when it says how long
    clock.now = 60
    await router.structured("default", "pick", MESSAGES, Pick)
    assert limited.calls == 1  # not asked again inside the wait
    clock.now = 91
    assert router.breaker("nim").state == "half_open"


def test_a_requested_wait_is_capped() -> None:
    now = [0.0]
    breaker = CircuitBreaker(max_wait_s=3600, clock=lambda: now[0])
    breaker.failure("gemini: HTTP 429", retry_after=86_400)
    now[0] = 3_000
    assert breaker.state == "open"
    now[0] = 3_601
    assert breaker.state == "half_open"


def test_breaker_closes_on_success() -> None:
    breaker = CircuitBreaker(threshold=1)
    breaker.failure("boom")
    assert breaker.state == "open"
    breaker.success()
    assert (breaker.state, breaker.failures, breaker.last_error) == ("closed", 0, None)


async def test_invalid_output_gets_one_repair_with_the_errors() -> None:
    fake = FakeProvider(script={"pick": ["not json at all", '{"choice": "fixed"}']})
    router = LLMRouter(_config(default=["fake"]), providers={"fake": fake})
    resets: list[int] = []
    result = await router.structured(
        "default", "pick", MESSAGES, Pick, on_reset=lambda: resets.append(1)
    )
    assert result.value.choice == "fixed"
    assert len(fake.calls) == 2
    repair_prompt = fake.calls[1]["messages"][-1].content
    assert "failed validation" in repair_prompt
    assert resets == [1]
    assert result.usage.output_tokens > 0


async def test_validator_errors_are_repaired_then_exhaust_the_chain() -> None:
    fake = FakeProvider(script={"pick": ['{"choice": "x"}', '{"choice": "y"}']})
    router = LLMRouter(_config(default=["fake"]), providers={"fake": fake})

    def only_z(value: Pick) -> list[str]:
        return [] if value.choice == "z" else [f"choice {value.choice} is not allowed"]

    with pytest.raises(StructuredOutputError) as info:
        await router.structured("default", "pick", MESSAGES, Pick, validator=only_z)
    assert "choice x is not allowed" in fake.calls[1]["messages"][-1].content
    assert [a["repair"] for a in info.value.attempts] == [0, 1]


async def test_schema_violations_are_reported_by_field() -> None:
    fake = FakeProvider(script={"pick": ['{"wrong": 1}', '{"choice": "ok"}']})
    router = LLMRouter(_config(default=["fake"]), providers={"fake": fake})
    await router.structured("default", "pick", MESSAGES, Pick)
    assert "choice: Field required" in fake.calls[1]["messages"][-1].content


async def test_empty_chain_raises_no_provider() -> None:
    router = LLMRouter(_config(default=["nim"]), providers={"nim": FailingProvider()})
    router.breaker("nim").failure("down", trip=True)
    with pytest.raises(NoProviderAvailableError):
        await router.structured("default", "pick", MESSAGES, Pick)


async def test_budget_limits_llm_calls_and_records_usage() -> None:
    fake = FakeProvider(script={"pick": ['{"choice": "a"}', '{"choice": "b"}']})
    router = LLMRouter(_config(default=["fake"]), providers={"fake": fake})
    budget = BudgetGuard(BudgetConfig(max_llm_calls=1))
    await router.structured("default", "pick", MESSAGES, Pick, budget=budget)
    assert budget.usage.llm_calls == 1
    assert budget.usage.tokens > 0
    with pytest.raises(BudgetExceededError) as info:
        await router.structured("default", "pick", MESSAGES, Pick, budget=budget)
    assert info.value.reason == "llm_calls"
    assert budget.usage.exhausted == ["llm_calls"]


def test_budget_guard_checks_every_limit() -> None:
    guard = BudgetGuard(
        BudgetConfig(max_tokens=100, max_cost_usd=0.01, max_tool_calls=1, max_steps=1)
    )
    with pytest.raises(BudgetExceededError, match="tokens"):
        guard.check_llm(estimated_tokens=500)
    guard.record_llm(Usage(input_tokens=10, output_tokens=5, cost_usd=0.02))
    with pytest.raises(BudgetExceededError, match="cost"):
        guard.check_llm()
    guard.record_tool()
    with pytest.raises(BudgetExceededError, match="tool_calls"):
        guard.check_tool()
    guard.record_step()
    with pytest.raises(BudgetExceededError, match="steps"):
        guard.check_step()
    guard.record_llm(Usage(input_tokens=1, output_tokens=1, cost_usd=None))
    snapshot = guard.snapshot()
    assert snapshot.cost_known is False
    assert snapshot.tokens == 17
    assert set(snapshot.exhausted) == {"tokens", "cost", "tool_calls", "steps"}


def test_budget_guard_enforces_wall_clock() -> None:
    guard = BudgetGuard(BudgetConfig(max_latency_s=0.000001))
    with pytest.raises(BudgetExceededError, match="latency"):
        guard.check_llm()


async def test_tokens_stream_through_the_callback() -> None:
    fake = FakeProvider(script={"pick": ['{"choice": "streamed value"}']})
    router = LLMRouter(_config(default=["fake"]), providers={"fake": fake})
    tokens: list[str] = []
    await router.structured("default", "pick", MESSAGES, Pick, on_token=tokens.append)
    assert "".join(tokens) == '{"choice": "streamed value"}'


async def test_complete_can_target_the_safety_model() -> None:
    class Recorder(FakeProvider):
        async def chat(self, messages: Any, **kwargs: Any) -> tuple[str, Usage]:
            self.calls.append(kwargs)
            return "safe", Usage(input_tokens=1, output_tokens=1)

    cfg = LLMConfig(
        providers={
            "nim": ProviderConfig(
                kind=ProviderKind.NVIDIA_NIM,
                base_url="http://n/v1",
                allow_no_key=True,
                chat_model="chat",
                safety_model="guard",
            )
        },
        safety=["nim"],
    )
    recorder = Recorder("nim")
    recorder.kind = ProviderKind.NVIDIA_NIM
    router = LLMRouter(cfg, providers={"nim": recorder})
    result = await router.complete("safety", MESSAGES, model_field="safety_model", chain=cfg.safety)
    assert result.value == "safe"
    assert result.model == "guard"
    assert recorder.calls[-1]["model"] == "guard"


async def test_embeddings_default_to_local_and_rerank_needs_a_provider() -> None:
    router = get_router()
    embedder = router.embedding_provider()
    assert embedder is not None
    assert isinstance(embedder.provider, LocalEmbeddingProvider)
    assert embedder.model.startswith(("hashing-", "lsa-"))
    vectors = await embedder.embed(["disk failure on node", "disk failure"])
    assert len(vectors) == 2
    assert await router.rerank("q", ["a"]) is None


def test_embedding_identity_is_the_embedding_model_not_the_chat_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-x")
    embedder = LLMRouter(get_app_config().llm).embedding_provider()
    assert embedder is not None
    assert embedder.model == "nim/nvidia/nemotron-3.5-embed-1b"


def test_status_lists_every_provider_with_its_roles() -> None:
    status = {s.name: s for s in get_router().status()}
    assert status["fake"].enabled
    assert not status["nim"].enabled
    assert "adjudicator" in status["nim"].roles
    assert "embeddings" in status["local"].roles
    assert status["nim"].chat_model


async def test_fake_provider_errors_on_unknown_tasks_and_raises_queued_errors() -> None:
    fake = FakeProvider()
    with pytest.raises(ProviderError):
        await fake.chat(MESSAGES, json_schema={"type": "object"}, schema_name="unknown")
    fake.queue("pick", ProviderError("scripted", status=500))
    with pytest.raises(ProviderError, match="scripted"):
        await fake.chat(MESSAGES, json_schema={}, schema_name="pick")
    text, _ = await fake.chat(MESSAGES)
    assert "offline" in text
    assert json.loads(json.dumps(fake.calls[0]["task"])) == "unknown"


def test_a_timeout_trips_the_breaker_at_once_and_for_longer() -> None:
    now = [0.0]
    breaker = CircuitBreaker(threshold=3, cooldown_s=30, trip_cooldown_s=300, clock=lambda: now[0])
    breaker.failure("nim: ReadTimeout", trip=True)
    states = [breaker.state]
    now[0] = 61
    states.append(breaker.state)
    now[0] = 301
    states.append(breaker.state)
    breaker.success()
    states.append(breaker.state)
    assert states == ["open", "open", "half_open", "closed"]
