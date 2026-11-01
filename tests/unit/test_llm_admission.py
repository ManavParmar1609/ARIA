"""The router around each request: admission against the ledger, one retry layer, replies cut
short or declined, schema step-downs counted as requests, and the response cache."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from aria.config import (
    LLMConfig,
    ProviderConfig,
    ProviderKind,
    ProviderLimits,
    QuotaConfig,
    get_app_config,
)
from aria.graph.workflow import TRANSIENT
from aria.llm.base import (
    LLMError,
    Message,
    NoProviderAvailableError,
    ProviderError,
    Usage,
)
from aria.llm.cache import ResponseCache, cache_key
from aria.llm.fake import FakeProvider
from aria.llm.quota import QuotaLedger
from aria.llm.router import LLMRouter
from aria.llm.visitor import VisitorKey

PACIFIC = ZoneInfo("America/Los_Angeles")
NOON = datetime(2026, 10, 30, 12, 0, tzinfo=PACIFIC).timestamp()
MESSAGES = [Message("system", "Pick one."), Message("user", "a or b?")]


class Pick(BaseModel):
    choice: str


class Model:
    """A real model (not the offline stand-in) that answers from a script: text, a (text,
    finish reason) pair, or an exception to raise."""

    kind = ProviderKind.OPENAI_COMPATIBLE

    def __init__(self, name: str, *script: Any) -> None:
        self.name, self.model = name, f"{name}-model"
        self.script: deque[Any] = deque(script)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages: Any, **kwargs: Any) -> tuple[str, Usage]:
        self.calls.append({"messages": list(messages), **kwargs})
        item = self.script.popleft() if self.script else '{"choice": "a"}'
        if isinstance(item, BaseException):
            raise item
        text, finish = item if isinstance(item, tuple) else (item, "stop")
        return text, Usage(input_tokens=10, output_tokens=5, finish_reason=finish)


def stand_in() -> FakeProvider:
    return FakeProvider(responders={"pick": lambda _ctx: {"choice": "offline"}})


def config(**limits: ProviderLimits) -> LLMConfig:
    def model(name: str) -> ProviderConfig:
        return ProviderConfig(
            kind=ProviderKind.OPENAI_COMPATIBLE,
            base_url=f"http://{name}/v1",
            allow_no_key=True,
            chat_model=f"{name}-model",
            limits=limits.get(name.replace("-", "_")),
        )

    return LLMConfig(
        providers={
            "gemini": model("gemini"),
            "gemini-lite": model("gemini-lite"),
            "fake": ProviderConfig(kind=ProviderKind.FAKE),
        },
        routing={"default": ["gemini", "gemini-lite", "fake"], "adjudicator": ["gemini"]},
        quota=QuotaConfig(margin=0.0),  # the limits as written, to keep the counts plain
    )


def router(cfg: LLMConfig, *models: Any, path: Path | None = None) -> LLMRouter:
    providers = {m.name: m for m in models}
    providers.setdefault("fake", stand_in())
    ledger = QuotaLedger.from_config(cfg, clock=lambda: NOON, path=path)
    return LLMRouter(cfg, providers=providers, ledger=ledger)


# --- admission ----------------------------------------------------------------------------------


async def test_a_full_model_is_skipped_for_the_next_and_the_skip_is_recorded(
    tmp_path: Path,
) -> None:
    gemini, lite = Model("gemini"), Model("gemini-lite")
    path = tmp_path / "llm-quota.json"
    llm = router(config(gemini=ProviderLimits(rpd=2)), gemini, lite, path=path)
    for _ in range(2):
        assert (await llm.structured("default", "pick", MESSAGES, Pick)).provider == "gemini"
    result = await llm.structured("default", "pick", MESSAGES, Pick)
    assert result.provider == "gemini-lite"
    skipped = result.attempts[0]
    assert skipped["provider"] == "gemini"
    assert skipped["skipped"] == "day"
    assert "no room" in skipped["error"]
    assert len(gemini.calls) == 2  # the full model never saw the third request
    saved = json.loads(path.read_text(encoding="utf-8"))  # counted before each request went
    assert saved["providers"]["gemini"]["day_requests"] == 2


async def test_when_every_model_is_full_the_caller_hears_so() -> None:
    llm = router(config(gemini=ProviderLimits(rpd=0)), Model("gemini"))
    with pytest.raises(NoProviderAvailableError, match="at its limit") as info:
        await llm.structured("adjudicator", "pick", MESSAGES, Pick)
    assert [a["skipped"] for a in info.value.attempts] == ["day"]


async def test_reported_tokens_replace_the_estimate() -> None:
    gemini = Model("gemini")
    llm = router(config(gemini=ProviderLimits(tpm=2_000)), gemini)
    await llm.structured("default", "pick", MESSAGES, Pick, max_tokens=1_500)
    room = {c.provider: c for c in llm.ledger.capacity()}["gemini"]
    assert room.minute_tokens_left == 2_000 - 15  # the 10 in and 5 out the model reported


# --- one retry layer ----------------------------------------------------------------------------


async def test_a_provider_failure_sends_one_request_then_the_next_provider_answers() -> None:
    """The router's fallback is the only retry for provider calls: one failure is one request
    to that provider, never several against the same limit."""
    broken = Model("gemini", ProviderError("gemini: ConnectError", retryable=True))
    lite = Model("gemini-lite")
    llm = router(config(gemini=ProviderLimits(rpm=10)), broken, lite)
    result = await llm.structured("default", "pick", MESSAGES, Pick)
    assert result.provider == "gemini-lite"
    assert len(broken.calls) == 1
    room = {c.provider: c for c in llm.ledger.capacity()}["gemini"]
    assert room.minute_requests_left == 9  # the failed request still counted


async def test_a_transport_error_a_client_lets_through_never_reaches_the_graph() -> None:
    """A raw transport error would set off the graph's node retry and rerun every call the
    node made. The router turns it into a fallback instead."""
    leaky = Model("gemini", httpx.ConnectError("connection reset"))
    llm = router(config(), leaky, Model("gemini-lite"))
    result = await llm.structured("default", "pick", MESSAGES, Pick)
    assert result.provider == "gemini-lite"
    assert len(leaky.calls) == 1
    # The node policy retries database and tool-server errors only: never a model call's.
    retried = TRANSIENT.retry_on
    assert isinstance(retried, tuple)
    assert not any(issubclass(kind, LLMError) for kind in retried)
    assert not issubclass(ProviderError, retried)


async def test_clients_are_built_to_send_each_request_once() -> None:
    from aria.llm.claude import ClaudeProvider

    claude = ClaudeProvider(
        "claude",
        get_app_config().llm.providers["claude"],
        api_key=SecretStr("sk-ant-test-0123456789abcdef"),
    )
    assert claude._sdk().max_retries == 0  # the SDK's own retries are off
    await claude.aclose()


# --- replies cut short, declined, or asked for again in another form ----------------------------


async def test_an_answer_cut_short_is_asked_for_once_more_with_twice_the_budget() -> None:
    gemini = Model("gemini", ('{"choice": ', "length"), '{"choice": "b"}')
    llm = router(config(), gemini)
    result = await llm.structured("default", "pick", MESSAGES, Pick, max_tokens=700)
    assert result.value.choice == "b"
    assert [c["max_tokens"] for c in gemini.calls] == [700, 1_400]
    assert gemini.calls[1]["messages"] == MESSAGES  # the same request, not a repair
    assert result.attempts[0] == {"provider": "gemini", "ok": False, "repair": 0, "stop": "length"}


async def test_an_answer_cut_short_twice_moves_on_without_a_repair() -> None:
    gemini = Model("gemini", ('{"choice": ', "length"), ('{"choice": ', "length"))
    lite = Model("gemini-lite")
    llm = router(config(), gemini, lite)
    result = await llm.structured("default", "pick", MESSAGES, Pick, max_tokens=700)
    assert result.provider == "gemini-lite"
    assert len(gemini.calls) == 2
    assert lite.calls[0]["max_tokens"] == 1_400  # the larger budget carries on


async def test_a_refusal_is_never_repaired_on_the_same_provider() -> None:
    gemini = Model("gemini", ProviderError("gemini: the model declined", refused=True))
    lite = Model("gemini-lite")
    llm = router(config(), gemini, lite)
    result = await llm.structured("default", "pick", MESSAGES, Pick)
    assert result.provider == "gemini-lite"
    assert len(gemini.calls) == 1
    assert result.attempts[0]["refused"] is True
    assert llm.breaker("gemini").failures == 0  # declining is not a fault


async def test_a_schema_step_down_is_sent_again_and_each_send_is_counted() -> None:
    gemini = Model(
        "gemini",
        ProviderError("gemini: HTTP 400: response_format", status=400, resend=True),
        '{"choice": "c"}',
    )
    llm = router(config(gemini=ProviderLimits(rpm=10)), gemini)
    result = await llm.structured("default", "pick", MESSAGES, Pick)
    assert (result.provider, result.value.choice) == ("gemini", "c")
    assert len(gemini.calls) == 2
    room = {c.provider: c for c in llm.ledger.capacity()}["gemini"]
    assert room.minute_requests_left == 8  # both sends counted against the limit
    assert llm.breaker("gemini").failures == 0


async def test_a_model_that_rejects_every_way_of_asking_for_json_is_left_after_four() -> None:
    rejected = ProviderError("gemini: HTTP 400: schema", status=400, resend=True)
    stubborn = Model("gemini", *([rejected] * 6))
    llm = router(config(), stubborn, Model("gemini-lite"))
    result = await llm.structured("default", "pick", MESSAGES, Pick)
    assert result.provider == "gemini-lite"
    assert len(stubborn.calls) == 4  # json_schema, guided_json, json_object, then the prompt
    assert "every way of asking for JSON" in result.attempts[0]["error"]


# --- the response cache -------------------------------------------------------------------------


async def test_identical_deterministic_requests_are_answered_from_memory() -> None:
    gemini = Model("gemini")
    llm = router(config(gemini=ProviderLimits(rpm=10)), gemini)
    first = await llm.structured("default", "pick", MESSAGES, Pick, temperature=0.0)
    again = await llm.structured("default", "pick", MESSAGES, Pick, temperature=0.0)
    assert (first.value, again.value) == (Pick(choice="a"), Pick(choice="a"))
    assert len(gemini.calls) == 1
    assert again.attempts[-1]["cached"] is True
    assert again.usage.cost_usd == 0.0
    room = {c.provider: c for c in llm.ledger.capacity()}["gemini"]
    assert room.minute_requests_left == 9  # an answer from memory spends no request
    # Sampling at a temperature is not deterministic: always asked.
    await llm.structured("default", "pick", MESSAGES, Pick, temperature=0.2)
    await llm.structured("default", "pick", MESSAGES, Pick, temperature=0.2)
    assert len(gemini.calls) == 3
    # The offline stand-in costs nothing: its answers are never kept.
    offline = stand_in()
    only_offline = LLMConfig(
        providers={"fake": ProviderConfig(kind=ProviderKind.FAKE)}, routing={"default": ["fake"]}
    )
    alone = LLMRouter(only_offline, providers={"fake": offline}, ledger=QuotaLedger({}))
    for _ in range(2):
        await alone.structured("default", "pick", MESSAGES, Pick, temperature=0.0)
    assert len(offline.calls) == 2
    assert len(alone.cache) == 0


def test_the_cache_key_covers_what_shapes_the_answer_and_keeps_no_text() -> None:
    base: dict[str, Any] = {
        "provider": "gemini",
        "model": "gemini-3.6-flash",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai",
        "mode": "json_schema",
        "messages": MESSAGES,
        "json_schema": {"type": "object"},
        "schema_name": "pick",
        "temperature": 0.0,
        "max_tokens": 700,
    }
    key = cache_key(**base)
    assert len(key) == 64
    assert "Pick one" not in key
    assert cache_key(**base) == key
    for field, other in (
        ("provider", "gemini-lite"),
        ("model", "gemini-3.5-flash-lite"),
        ("mode", "prompt"),
        ("messages", [Message("user", "a or c?")]),
        ("json_schema", {"type": "array"}),
        ("max_tokens", 1_400),
    ):
        assert cache_key(**{**base, field: other}) != key, field


def test_the_cache_forgets_after_its_time_and_keeps_at_most_its_size() -> None:
    now = [0.0]
    cache = ResponseCache(ttl_s=60, max_entries=2, clock=lambda: now[0])
    usage = Usage(input_tokens=1, output_tokens=1)
    for name in ("a", "b", "c"):
        cache.put(name, f"answer {name}", usage)
    assert len(cache) == 2
    assert cache.get("a") is None  # the oldest went first
    hit = cache.get("c")
    assert hit is not None
    assert hit[0] == "answer c"
    assert hit[1].cached
    now[0] = 61
    assert cache.get("c") is None
    assert not ResponseCache(ttl_s=0, max_entries=10).enabled


async def test_work_on_a_visitors_key_is_never_cached_or_counted() -> None:
    """A visitor's key spends the visitor's limits: the server's ledger never counts it, and
    its answers are never kept, so no other visitor (or the server) is answered from them."""
    llm_config = get_app_config().llm
    shared = Model("gemini")
    llm = LLMRouter(
        llm_config,
        providers={"gemini": shared, "fake": stand_in()},
        ledger=QuotaLedger.from_config(llm_config, clock=lambda: NOON),
    )
    view = llm.with_key(VisitorKey("gemini", SecretStr("AIza-visitor-0123456789")))
    own = Model("gemini")
    view._own["gemini"] = own
    for _ in range(2):
        result = await view.structured("reporter", "pick", MESSAGES, Pick, temperature=0.0)
        assert result.provider == "gemini"
    assert len(own.calls) == 2  # asked each time: nothing kept
    assert len(llm.cache) == 0
    room = {c.provider: c for c in llm.ledger.capacity()}["gemini"]
    assert room.day_requests_used == 0
    await llm.structured("reporter", "pick", MESSAGES, Pick, temperature=0.0)
    assert len(shared.calls) == 1  # the server's own call was not answered from the visitor's
