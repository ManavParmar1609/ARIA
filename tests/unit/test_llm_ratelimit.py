"""Refusals for a limit, told apart: a per-minute limit, a daily quota, a spending cap, an empty
account and a busy provider, as each provider words them (mocked HTTP), and what the router
does with each: how long the provider rests, in the ledger and its breaker, and what is logged."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import httpx2
import pytest
import respx
from pydantic import BaseModel, SecretStr

from aria.config import LLMConfig, ProviderConfig, ProviderKind, ProviderLimits, get_app_config
from aria.llm import router as router_module
from aria.llm.base import Message, ProviderError, RateLimit, Usage
from aria.llm.claude import ClaudeProvider
from aria.llm.fake import FakeProvider
from aria.llm.openai_compat import OpenAICompatibleProvider
from aria.llm.quota import QuotaLedger, next_reset
from aria.llm.ratelimit import classify, retry_after_seconds
from aria.llm.router import LLMRouter
from aria.llm.visitor import VisitorKey

GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"
PACIFIC = ZoneInfo("America/Los_Angeles")
NOON = datetime(2026, 10, 30, 12, 0, tzinfo=PACIFIC).timestamp()
MESSAGES = [Message("user", "pick one")]


def gemini_429(quota_id: str, delay: str = "41s") -> list[dict[str, Any]]:
    """Gemini's OpenAI-compatible endpoint answers a quota refusal with a list of errors."""
    return [
        {
            "error": {
                "code": 429,
                "message": "You exceeded your current quota, please check your plan and billing "
                "details. * Quota exceeded for metric: generativelanguage.googleapis.com/"
                "generate_content_free_tier_requests, limit: 20, model: gemini-3.6-flash",
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaMetric": "generativelanguage.googleapis.com/"
                                "generate_content_free_tier_requests",
                                "quotaId": quota_id,
                                "quotaDimensions": {"model": "gemini-3.6-flash"},
                                "quotaValue": "20",
                            }
                        ],
                    },
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay},
                ],
            }
        }
    ]


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch) -> OpenAICompatibleProvider:
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test-key-0123456789")
    return OpenAICompatibleProvider("gemini", get_app_config().llm.providers["gemini"])


async def refusal(provider: OpenAICompatibleProvider, status: int, **reply: Any) -> ProviderError:
    with respx.mock:
        route = respx.post(f"{GEMINI}/chat/completions").mock(
            return_value=httpx.Response(status, **reply)
        )
        with pytest.raises(ProviderError) as info:
            await provider.chat(MESSAGES)
        assert route.call_count == 1  # never retried inside the client
    return info.value


# --- telling them apart -----------------------------------------------------------------------


async def test_a_gemini_daily_quota_is_not_mistaken_for_its_retry_delay(
    gemini: OpenAICompatibleProvider,
) -> None:
    """Waiting the 41 seconds Gemini names would not help: the day's quota is gone."""
    error = await refusal(
        gemini, 429, json=gemini_429("GenerateRequestsPerDayPerProjectPerModel-FreeTier")
    )
    assert error.limit is not None
    assert error.limit.kind == "day"
    assert error.retry_after == 41.0


async def test_a_gemini_per_minute_limit_names_its_delay(gemini: OpenAICompatibleProvider) -> None:
    error = await refusal(
        gemini,
        429,
        json=gemini_429("GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "7.5s"),
    )
    assert error.limit is not None
    assert (error.limit.kind, error.limit.retry_after) == ("minute", 7.5)


async def test_openai_insufficient_quota_means_no_credit(gemini: OpenAICompatibleProvider) -> None:
    body = {
        "error": {
            "message": "You exceeded your current quota, please check your plan and billing "
            "details.",
            "type": "insufficient_quota",
            "param": None,
            "code": "insufficient_quota",
        }
    }
    error = await refusal(gemini, 429, json=body)
    assert error.limit is not None
    assert error.limit.kind == "no_credit"


async def test_a_window_named_in_words_is_read_too(gemini: OpenAICompatibleProvider) -> None:
    """Groq and OpenAI name the window in the message."""
    day = {
        "error": {
            "message": "Rate limit reached for model `openai/gpt-oss-20b` on requests per day "
            "(RPD): Limit 1000, Used 1000, Requested 1. Please try again in 1m26.4s.",
            "type": "requests",
            "code": "rate_limit_exceeded",
        }
    }
    error = await refusal(gemini, 429, json=day)
    assert error.limit is not None
    assert error.limit.kind == "day"
    minute = {"error": {"message": "Rate limit reached on tokens per minute (TPM)"}}
    error = await refusal(gemini, 429, json=minute, headers={"retry-after": "3"})
    assert error.limit is not None
    assert (error.limit.kind, error.limit.retry_after) == ("minute", 3.0)


async def test_a_busy_provider_is_not_an_account_limit(gemini: OpenAICompatibleProvider) -> None:
    error = await refusal(gemini, 503, json={"error": {"message": "The model is overloaded."}})
    assert error.limit is not None
    assert error.limit.kind == "overload"
    error = await refusal(gemini, 400, json={"error": {"message": "Invalid argument"}})
    assert error.limit is None
    error = await refusal(gemini, 401, json={"error": {"message": "API key not valid"}})
    assert error.limit is None


def test_retry_after_reads_seconds_dates_and_gemini_delays() -> None:
    now = datetime(2026, 10, 30, 12, 0, tzinfo=ZoneInfo("UTC")).timestamp()
    assert retry_after_seconds({"retry-after": "12"}, "", now=now) == 12.0
    date = "Fri, 30 Oct 2026 12:01:00 GMT"
    assert retry_after_seconds({"retry-after": date}, "", now=now) == 60.0
    assert retry_after_seconds({}, '{"retryDelay": "0.5s"}', now=now) == 0.5
    assert retry_after_seconds({}, "busy", now=now) is None


def test_a_spending_cap_message_says_when_access_returns() -> None:
    body = json.dumps(
        {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "message": "You have reached your specified API usage limits. You will regain "
                "access on 2026-11-01 at 00:00 UTC.",
            },
        }
    )
    limit = classify(400, body, {}, now=NOON, anthropic=True)
    assert limit is not None
    assert limit.kind == "spend_cap"
    assert limit.until == datetime(2026, 11, 1, tzinfo=ZoneInfo("UTC")).timestamp()


# --- Claude -------------------------------------------------------------------------------------


def _claude(handler: Any) -> ClaudeProvider:
    cfg = get_app_config().llm.providers["claude"]
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    key = SecretStr("sk-ant-test-0123456789abcdef")
    return ClaudeProvider("claude", cfg, api_key=key, http_client=client)


async def claude_refusal(
    status: int, body: dict[str, Any], headers: dict[str, str]
) -> ProviderError:
    calls: list[int] = []

    def handler(_: httpx2.Request) -> httpx2.Response:
        calls.append(1)
        return httpx2.Response(status, json=body, headers=headers)

    with pytest.raises(ProviderError) as info:
        await _claude(handler).chat(MESSAGES)
    assert len(calls) == 1  # the SDK's own retries are off: one request per call
    return info.value


async def test_claude_rate_limits_and_spend_limits_are_told_apart() -> None:
    rate = {"type": "error", "error": {"type": "rate_limit_error", "message": "Rate limited"}}
    error = await claude_refusal(429, rate, {"retry-after": "20"})
    assert error.limit is not None
    assert (error.limit.kind, error.limit.retry_after) == ("minute", 20.0)
    # Anthropic's rate limits always say when to retry; its spend limit does not.
    error = await claude_refusal(429, rate, {})
    assert error.limit is not None
    assert error.limit.kind == "spend_cap"
    low = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "Your credit balance is too low to access the Anthropic API.",
        },
    }
    error = await claude_refusal(400, low, {})
    assert error.limit is not None
    assert error.limit.kind == "no_credit"
    assert not error.resend  # not a schema problem: no second request in another form
    busy = {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
    error = await claude_refusal(529, busy, {})
    assert error.limit is not None
    assert error.limit.kind == "overload"


# --- what the router does with each -------------------------------------------------------------


class Pick(BaseModel):
    choice: str


def stand_in() -> FakeProvider:
    return FakeProvider(responders={"pick": lambda _ctx: {"choice": "offline"}})


class Logged:
    """Stands in for the router's logger: what it said, at which level."""

    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}

    def _record(self, level: str, event: str, **fields: Any) -> None:
        self.events[event] = {"level": level, **fields}

    def info(self, event: str, **fields: Any) -> None:
        self._record("info", event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._record("warning", event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._record("error", event, **fields)


class Refuses:
    """A real model that refuses for ``limit`` once, then answers."""

    kind = ProviderKind.OPENAI_COMPATIBLE
    model = "gemini-3.6-flash"

    def __init__(self, limit: RateLimit, name: str = "gemini") -> None:
        self.name = name
        self.limit = limit
        self.calls = 0

    async def chat(self, messages: Any, **_: Any) -> tuple[str, Usage]:
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("gemini: HTTP 429", status=429, limit=self.limit)
        return '{"choice": "a"}', Usage(input_tokens=5, output_tokens=5)


def _router(limit: RateLimit, clock: list[float]) -> tuple[LLMRouter, Refuses]:
    config = LLMConfig(
        providers={
            "gemini": ProviderConfig(
                kind=ProviderKind.OPENAI_COMPATIBLE,
                base_url=GEMINI,
                allow_no_key=True,
                chat_model="gemini-3.6-flash",
                limits=ProviderLimits(rpm=100, rpd=1_000),
            ),
            "fake": ProviderConfig(kind=ProviderKind.FAKE),
        },
        routing={"default": ["gemini", "fake"]},
    )
    model = Refuses(limit)
    ledger = QuotaLedger.from_config(config, clock=lambda: clock[0])
    router = LLMRouter(
        config,
        providers={"gemini": model, "fake": stand_in()},
        ledger=ledger,
        clock=lambda: clock[0],
    )
    return router, model


@pytest.mark.parametrize(
    ("limit", "rests_for"),
    [
        (RateLimit("minute", "its per-minute limit is reached", retry_after=41), 41.0),
        (RateLimit("day", "its daily quota is used up", retry_after=41), None),  # to the reset
        (RateLimit("spend_cap", "the account's spending cap is reached"), None),
        (RateLimit("no_credit", "the account has no credit or quota left"), None),
        (RateLimit("overload", "the provider is busy (HTTP 503)"), 15.0),
    ],
)
async def test_each_refusal_rests_the_provider_for_as_long_as_its_limit_lasts(
    limit: RateLimit, rests_for: float | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [NOON]
    router, model = _router(limit, clock)
    logged = Logged()
    monkeypatch.setattr(router_module, "log", logged)
    result = await router.structured("default", "pick", MESSAGES, Pick)
    assert result.provider == "fake"  # the next provider took the call
    assert result.attempts[0]["limit"] == limit.kind
    held = router.ledger.held("gemini")
    assert held is not None
    until = NOON + rests_for if rests_for is not None else next_reset(NOON, PACIFIC)
    assert held[0] == until
    assert router.breaker("gemini").state == "open"
    clock[0] = until - 1
    result = await router.structured("default", "pick", MESSAGES, Pick)
    assert result.provider == "fake"
    assert model.calls == 1  # not asked again while it rests
    clock[0] = until
    result = await router.structured("default", "pick", MESSAGES, Pick)
    assert result.provider == "gemini"  # back once the limit has lifted
    if limit.kind in ("spend_cap", "no_credit"):
        said = logged.events["llm.spend_cap"]
        assert said["level"] == "error"
        assert "stopped answering" in said["message"]
        assert "Raise the cap or add credit" in said["message"]
    elif limit.kind == "day":
        said = logged.events["llm.daily_quota_used"]
        assert said["level"] == "warning"
        assert "used its daily quota" in said["message"]
    else:
        assert logged.events["llm.rate_limited"]["level"] == "info"


async def test_a_visitors_limit_rests_only_their_own_view() -> None:
    """A refusal on a visitor's key is the visitor's limit: it never holds this server's model."""
    clock = [NOON]
    config = get_app_config().llm
    router = LLMRouter(
        config,
        providers={"fake": stand_in()},
        ledger=QuotaLedger.from_config(config, clock=lambda: clock[0]),
    )
    view = router.with_key(VisitorKey("gemini", SecretStr("AIza-visitor-0123456789")))
    for name in ("gemini", "gemini-lite", "gemini-lite-2", "gemma"):
        view._own[name] = Refuses(RateLimit("day", "its daily quota is used up"), name)
    result = await view.structured("reporter", "pick", MESSAGES, Pick)
    assert result.provider == "fake"
    assert router.ledger.held("gemini") is None  # the server's own model is untouched
    assert router.breaker("gemini").state == "closed"
    assert view.breaker("gemini").state == "open"
