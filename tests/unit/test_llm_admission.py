"""The router around each request: admission against the ledger, one retry layer, replies cut
short or declined, schema step-downs counted as requests, and the response cache."""

from __future__ import annotations

import json
from collections import Counter, deque
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import httpx2
import pytest
from pydantic import BaseModel, SecretStr

from aria.config import (
    BudgetConfig,
    LLMConfig,
    ProviderConfig,
    ProviderKind,
    ProviderLimits,
    QuotaConfig,
    get_app_config,
)
from aria.contracts.inputs import TriageRequest
from aria.contracts.run import RunStatus
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.db import repository as repo
from aria.db.engine import get_engine, init_db
from aria.graph.runner import TriageRunner
from aria.graph.workflow import TRANSIENT
from aria.llm.base import (
    LLMError,
    Message,
    ModelRefusalError,
    NoProviderAvailableError,
    OutputTruncatedError,
    ProviderError,
    StructuredOutputError,
    Usage,
)
from aria.llm.budget import BudgetGuard
from aria.llm.cache import ResponseCache, cache_key
from aria.llm.claude import ClaudeProvider
from aria.llm.fake import FakeProvider
from aria.llm.quota import QuotaLedger
from aria.llm.router import LLMRouter
from aria.llm.visitor import VisitorKey
from aria.services import Services

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"
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
    claude = ClaudeProvider(
        "claude",
        get_app_config().llm.providers["claude"],
        api_key=SecretStr("sk-ant-test-0123456789abcdef"),
    )
    assert claude._sdk().max_retries == 0  # the SDK's own retries are off
    await claude.aclose()


class BreaksMidStream(httpx2.AsyncByteStream):
    """A Claude stream whose connection drops after the first event."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        start = {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-opus-5-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 12, "output_tokens": 1},
            },
        }
        yield f"event: message_start\ndata: {json.dumps(start)}\n\n".encode()
        msg = "peer closed the connection mid-stream"
        raise httpx2.ReadError(msg)


def breaking_claude(requests: list[int]) -> ClaudeProvider:
    def handler(_: httpx2.Request) -> httpx2.Response:
        requests.append(1)
        headers = {"content-type": "text/event-stream"}
        return httpx2.Response(200, headers=headers, stream=BreaksMidStream())

    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return ClaudeProvider(
        "claude",
        get_app_config().llm.providers["claude"],
        api_key=SecretStr("sk-ant-test-0123456789abcdef"),
        http_client=client,
    )


async def test_a_claude_stream_that_breaks_falls_over_after_one_request() -> None:
    """Anthropic's SDK reads a stream with httpx2 and lets a broken stream's error through as it
    is. The client turns it into a provider error, so the router's fallback (the one retry
    layer) moves on, instead of the error escaping to the graph, where nothing retries it."""
    requests: list[int] = []
    claude = breaking_claude(requests)
    with pytest.raises(ProviderError) as info:
        await claude.chat(MESSAGES, json_schema={"type": "object"})
    assert info.value.retryable
    assert requests == [1]
    cfg = LLMConfig(
        providers={
            "claude": get_app_config().llm.providers["claude"],
            "fake": ProviderConfig(kind=ProviderKind.FAKE),
        },
        routing={"default": ["claude", "fake"]},
        data_terms=get_app_config().llm.data_terms,
    )
    llm = LLMRouter(cfg, providers={"claude": claude, "fake": stand_in()}, ledger=QuotaLedger({}))
    result = await llm.structured("default", "pick", MESSAGES, Pick)
    assert result.provider == "fake"
    assert requests == [1, 1]  # one request for this call, then the next provider
    assert result.attempts[0]["provider"] == "claude"
    await claude.aclose()


async def test_a_transport_error_is_sent_once_per_call_and_never_reruns_a_step() -> None:
    """Counted end to end: every model call the run makes reaches the broken provider exactly
    once (the SDK does not retry), the router then hands it to the next provider (the one retry
    layer), and no step of the graph runs twice (the node policy never retries a model call)."""
    requests: list[int] = []
    claude = breaking_claude(requests)
    roles = ("adjudicator", "investigator", "reporter", "critic", "comms", "retriever", "default")
    cfg = get_app_config().llm.model_copy(
        update={
            "routing": {
                role: ["claude"] if role == "adjudicator" else ["claude", "fake"] for role in roles
            }
        }
    )
    # A high breaker threshold keeps the broken provider in every chain, so each call is seen.
    llm = LLMRouter(
        cfg,
        providers={"claude": claude, "fake": FakeProvider()},
        ledger=QuotaLedger({}),
        breaker_threshold=1_000,
    )
    init_db(get_engine())
    services = await Services.create(router=llm)
    assessed: list[int] = []
    assess = services.severity.assess

    async def counted(*args: Any, **kwargs: Any) -> Any:
        assessed.append(1)
        return await assess(*args, **kwargs)

    services.severity.assess = counted  # type: ignore[method-assign]
    try:
        builder = ScenarioBuilder(LinePools.from_loghub(FIXTURES))
        scenario = builder.build(
            "bgl.kernel_panic", seed=8, nodes=4, duration_min=6, incident_per_min=8
        )
        request = TriageRequest(title="Kernel panics", system="bgl", logs=scenario.lines)
        outcome = await TriageRunner(services).start(request)
    finally:
        await services.aclose()
    assert outcome.status is RunStatus.AWAITING_REVIEW  # the run fell over, it did not fail
    events = repo.list_events(get_engine(), outcome.run_id)
    to_claude = [
        e for e in events if e.kind == "llm_call" and e.payload.get("provider") == "claude"
    ]
    assert to_claude  # the run did ask the broken provider
    assert all(e.payload.get("error") for e in to_claude)
    assert len(requests) == len(to_claude)  # one request per call: no retry in the client
    # The severity step's model call (the adjudicator's, on the broken provider alone) failed,
    # and the step still ran once: the graph retried nothing.
    assert assessed == [1]
    assert not [e for e in events if e.kind == "error"]
    started = Counter(e.node for e in events if e.kind == "node_started")
    replan_loop = {"investigate", "assess", "widen"}  # a replan runs these again, by design
    assert all(count == 1 for node, count in started.items() if node not in replan_loop)


# --- replies cut short, declined, or asked for again in another form ----------------------------


async def test_an_answer_cut_short_is_asked_for_once_more_with_twice_the_budget() -> None:
    gemini = Model("gemini", ('{"choice": ', "length"), '{"choice": "b"}')
    llm = router(config(), gemini)
    result = await llm.structured("default", "pick", MESSAGES, Pick, max_tokens=700)
    assert result.value.choice == "b"
    assert [c["max_tokens"] for c in gemini.calls] == [700, 1_400]
    assert gemini.calls[1]["messages"] == MESSAGES  # the same request, not a repair
    first = result.attempts[0]
    assert {k: first[k] for k in ("provider", "ok", "repair", "stop")} == {
        "provider": "gemini",
        "ok": False,
        "repair": 0,
        "stop": "length",
    }


async def test_an_answer_cut_short_twice_moves_on_without_a_repair() -> None:
    gemini = Model("gemini", ('{"choice": ', "length"), ('{"choice": ', "length"))
    lite = Model("gemini-lite")
    llm = router(config(), gemini, lite)
    result = await llm.structured("default", "pick", MESSAGES, Pick, max_tokens=700)
    assert result.provider == "gemini-lite"
    assert len(gemini.calls) == 2
    assert lite.calls[0]["max_tokens"] == 1_400  # the larger budget carries on


async def test_a_reply_cut_short_is_never_parsed_even_when_it_is_valid_json() -> None:
    """The router checks how every reply ended itself, so a client that hands back JSON cut
    short (and one that passes the provider's own word for it) never has it parsed."""
    gemini = Model("gemini", ('{"choice": "x"}', "length"), ('{"choice": "y"}', "max_tokens"))
    lite = Model("gemini-lite")
    llm = router(config(), gemini, lite)
    result = await llm.structured("default", "pick", MESSAGES, Pick, max_tokens=700)
    assert (result.provider, result.value.choice) == ("gemini-lite", "a")
    assert [a.get("stop") for a in result.attempts[:2]] == ["length", "length"]
    assert llm.breaker("gemini").failures == 0  # a long answer is no fault of the provider


async def test_a_cut_or_a_refusal_ends_on_the_deterministic_path_with_its_cost_counted() -> None:
    """Typed stops are failures like any other: when no provider is left the caller hears a
    StructuredOutputError (an LLMError) and takes its deterministic path. The tokens each
    declined or cut-short reply was billed still count against the run's budget."""
    cut = OutputTruncatedError("gemini: cut short", usage=Usage(input_tokens=40, output_tokens=700))
    gemini = Model("gemini", cut, cut)
    llm = router(config(), gemini)
    budget = BudgetGuard(BudgetConfig())
    with pytest.raises(StructuredOutputError) as info:
        await llm.structured("adjudicator", "pick", MESSAGES, Pick, budget=budget, max_tokens=700)
    assert isinstance(info.value, LLMError)
    assert [c["max_tokens"] for c in gemini.calls] == [700, 1_400]
    assert [a["stop"] for a in info.value.attempts] == ["length", "length"]
    assert (budget.usage.tokens_in, budget.usage.tokens_out) == (80, 1_400)
    assert llm.breaker("gemini").failures == 0

    declined = ModelRefusalError(
        "gemini: declined",
        reason="content_filter",
        usage=Usage(input_tokens=40, finish_reason="content_filter"),
    )
    refusing = Model("gemini", declined, '{"choice": "never asked"}')
    llm = router(config(), refusing)
    budget = BudgetGuard(BudgetConfig())
    with pytest.raises(StructuredOutputError) as info:
        await llm.structured("adjudicator", "pick", MESSAGES, Pick, budget=budget)
    assert len(refusing.calls) == 1  # neither repaired nor asked again
    assert info.value.attempts[0]["refused"] is True
    assert budget.usage.tokens_in == 40
    assert budget.calls[-1]["stop"] == "refusal"  # the run's call list says what happened


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
