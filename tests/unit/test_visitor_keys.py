"""Visitors' own model keys: checked on arrival, used for their own work, stored nowhere."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest
import respx
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from pydantic import SecretStr, ValidationError
from sqlalchemy import select

from aria.api.app import create_app
from aria.config import (
    LLMConfig,
    StructuredOutputMode,
    get_app_config,
    reset_caches,
)
from aria.data.scenarios import LinePools, ScenarioBuilder
from aria.db.engine import get_engine, init_db
from aria.db.models import Base
from aria.llm.base import Message, ProviderError
from aria.llm.claude import ClaudeProvider
from aria.llm.openai_compat import OpenAICompatibleProvider
from aria.llm.router import LLMRouter
from aria.llm.visitor import VisitorKey, VisitorKeys, parse_key

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "loghub"
GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai"
OPENAI = "https://api.openai.com/v1"
ANTHROPIC = "https://api.anthropic.com"
KEY = "AIzaVisitorKey-0123456789abcdefghijklmno"  # shaped like a Google key, not a real one
SCHEMA = {
    "type": "object",
    "properties": {"x": {"type": "integer"}},
    "required": ["x"],
    "additionalProperties": False,
}
MESSAGES = [Message("system", "be terse"), Message("user", "give x")]


def visitor(provider: str = "gemini", key: str = KEY) -> VisitorKey:
    return VisitorKey(provider, SecretStr(key))


# --- the registry and the key's shape --------------------------------------------------------


def test_a_key_is_held_until_its_run_starts_then_forgotten() -> None:
    keys = VisitorKeys()
    keys.hold("run-1", visitor())
    assert len(keys) == 1
    taken = keys.take("run-1")
    assert taken is not None
    assert taken.key.get_secret_value() == KEY
    assert keys.take("run-1") is None
    assert len(keys) == 0


def test_keys_left_waiting_too_long_or_past_the_cap_are_dropped() -> None:
    now = [0.0]
    keys = VisitorKeys(hold_s=60, limit=2, clock=lambda: now[0])
    keys.hold("old", visitor())
    now[0] = 30
    keys.hold("newer", visitor())
    now[0] = 50
    keys.hold("newest", visitor())  # over the cap: the oldest goes
    assert keys.take("old") is None
    now[0] = 95  # "newer" waited past its 60 s, "newest" did not
    assert keys.take("newer") is None
    assert keys.take("newest") is not None


@pytest.mark.parametrize(
    "value",
    ["", "short", "x" * 201, KEY + "\r\nX-Injected: 1", "has spaces in it 0123456789", "ké" * 20],
)
def test_only_a_plain_token_counts_as_a_key(value: str) -> None:
    assert parse_key(value) is None


def test_a_key_never_shows_in_its_own_repr() -> None:
    parsed = parse_key(f"  {KEY}  ")
    assert parsed is not None
    assert parsed.get_secret_value() == KEY
    assert KEY not in repr(visitor())
    assert KEY not in str(visitor())


def test_visitor_keys_only_fill_providers_that_take_an_api_key() -> None:
    base = get_app_config().llm.model_dump()
    assert LLMConfig.model_validate(base).visitor_keys.accepted() == []  # off by default
    for wrong in (["fake"], ["local"], ["missing"], []):
        broken = {**base, "visitor_keys": {"enabled": True, "providers": {"gemini": wrong}}}
        with pytest.raises(ValidationError):
            LLMConfig.model_validate(broken)
    on = {**base, "visitor_keys": {**base["visitor_keys"], "enabled": True}}
    assert LLMConfig.model_validate(on).visitor_keys.accepted() == [
        "claude",
        "gemini",
        "openai",
        "nvidia",
    ]


# --- the router's view for one key -----------------------------------------------------------


async def test_a_key_view_leads_with_its_providers_and_keeps_its_failures_to_itself() -> None:
    router = LLMRouter(get_app_config().llm)
    assert not router.is_set_up("gemini")  # this server has no Gemini key
    view = router.with_key(visitor())
    assert view.chain("reporter")[:2] == ["gemini", "gemini-lite"]
    assert view.has_real_llm("reporter")
    provider = view.provider("gemini")
    assert isinstance(provider, OpenAICompatibleProvider)
    headers = await provider._headers()
    assert headers["Authorization"] == f"Bearer {KEY}"
    view.breaker("gemini").failure("HTTP 503", trip=True)
    assert not view.is_available("gemini")
    assert router.breaker("gemini").state == "closed"  # the server's breaker never heard of it
    assert all(s.last_error is None for s in router.status())
    shared = router.provider("fake")
    await view.aclose()
    assert view.provider("gemini")._client.is_closed
    assert router.provider("fake") is shared  # nothing of the server's was closed
    assert router.chain("reporter")[0] != "gemini"


async def test_each_kind_of_key_fills_its_own_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    router = LLMRouter(get_app_config().llm)
    assert isinstance(router.with_key(visitor("claude")).provider("claude"), ClaudeProvider)
    for kind, first in (("openai", "openai"), ("nvidia", "nim"), ("claude", "claude")):
        assert router.with_key(visitor(kind)).chain("adjudicator")[0] == first
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server-key-0123456789")
    reset_caches()
    assert isinstance(LLMRouter(get_app_config().llm).provider("claude"), ClaudeProvider)


def test_reasoning_models_get_max_completion_tokens_and_no_temperature() -> None:
    openai = get_app_config().llm.providers["openai"]
    payload = OpenAICompatibleProvider("openai", openai, api_key=SecretStr(KEY))._payload(
        MESSAGES,
        json_schema=SCHEMA,
        schema_name="thing",
        temperature=0.1,
        max_tokens=300,
        stream=True,
        mode=StructuredOutputMode.JSON_SCHEMA,
        model="gpt-6.1-sol",
    )
    assert "temperature" not in payload
    assert "max_tokens" not in payload
    assert payload["max_completion_tokens"] == 300 + openai.reasoning_tokens
    assert payload["reasoning_effort"] == "low"


@respx.mock
async def test_a_provider_that_echoes_the_key_never_gets_it_into_an_error() -> None:
    respx.post(f"{GEMINI}/chat/completions").mock(
        return_value=httpx.Response(400, json={"error": {"message": f"API key {KEY} not valid"}})
    )
    cfg = get_app_config().llm.providers["gemini"]
    provider = OpenAICompatibleProvider("gemini", cfg, api_key=SecretStr(KEY))
    with pytest.raises(ProviderError) as caught:
        await provider.chat(MESSAGES)
    assert KEY not in str(caught.value)
    assert "[key]" in str(caught.value)
    await provider.aclose()


# --- Claude through Anthropic's SDK ----------------------------------------------------------


def _claude_stream(text: str, stop_reason: str = "end_turn") -> str:
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "message_start",
            {
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
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": text},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 7},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


def _claude(handler: Any, key: str = "sk-ant-visitor-0123456789abcdef") -> ClaudeProvider:
    cfg = get_app_config().llm.providers["claude"]
    client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    return ClaudeProvider("claude", cfg, api_key=SecretStr(key), http_client=client)


async def test_claude_gets_its_schema_and_system_prompt_the_way_anthropic_documents() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_claude_stream('{"x": 1}').encode(),
        )

    tokens: list[str] = []
    provider = _claude(handler)
    text, usage = await provider.chat(MESSAGES, json_schema=SCHEMA, on_token=tokens.append)
    assert json.loads(text) == {"x": 1}
    assert "".join(tokens) == text
    assert (usage.input_tokens, usage.output_tokens) == (12, 7)
    assert usage.cost_usd is not None
    assert usage.cost_usd > 0
    body = json.loads(seen[0].content)
    assert body["system"] == "be terse"
    assert body["messages"] == [{"role": "user", "content": "give x"}]
    assert body["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": SCHEMA},
    }
    assert "temperature" not in body
    assert body["max_tokens"] == 1_500 + provider.config.reasoning_tokens
    assert body["fallbacks"] == "default"
    assert seen[0].headers["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert "sk-ant-visitor-0123456789abcdef" in seen[0].headers.get("authorization", "") + (
        seen[0].headers.get("x-api-key", "")
    )
    await provider.aclose()


async def test_a_claude_refusal_or_rejected_key_hands_the_call_on() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_claude_stream("", stop_reason="refusal").encode(),
        )

    with pytest.raises(ProviderError, match="declined"):
        await _claude(refuse).chat(MESSAGES)

    key = "sk-ant-visitor-echoed-0123456789"

    def reject(request: httpx2.Request) -> httpx2.Response:
        error = {"type": "authentication_error", "message": f"invalid x-api-key {key}"}
        return httpx2.Response(401, json={"type": "error", "error": error})

    with pytest.raises(ProviderError) as caught:
        await _claude(reject, key=key).chat(MESSAGES)
    assert caught.value.status == 401
    assert not caught.value.retryable
    assert key not in str(caught.value)


async def test_claude_asks_for_the_schema_in_words_when_it_cannot_constrain_to_it() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "format" in body.get("output_config", {}):
            error = {"type": "invalid_request_error", "message": "output_config.format: schema"}
            return httpx2.Response(400, json={"type": "error", "error": error})
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_claude_stream('{"x": 2}').encode(),
        )

    provider = _claude(handler)
    text, _ = await provider.chat(MESSAGES, json_schema=SCHEMA)
    assert json.loads(text) == {"x": 2}
    assert "JSON Schema" in bodies[-1]["system"]
    assert provider.mode is StructuredOutputMode.PROMPT


async def test_claude_lists_its_models_for_a_key_check() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/models"
        return httpx2.Response(
            200,
            json={
                "data": [
                    {
                        "type": "model",
                        "id": "claude-opus-5-5",
                        "display_name": "Claude Opus 5.5",
                        "created_at": "2026-09-01T00:00:00Z",
                    }
                ],
                "has_more": False,
                "first_id": "claude-opus-5-5",
                "last_id": "claude-opus-5-5",
            },
        )

    assert await _claude(handler).list_models() == ["claude-opus-5-5"]


# --- over HTTP --------------------------------------------------------------------------------


async def _app(monkeypatch: pytest.MonkeyPatch, **env: str) -> AsyncIterator[httpx.AsyncClient]:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    reset_caches()
    init_db(get_engine())
    app: FastAPI = create_app()
    async with LifespanManager(app) as manager:
        transport = httpx.ASGITransport(app=manager.app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost:8000", timeout=60
        ) as client:
            client.app = app  # type: ignore[attr-defined]
            yield client


@pytest.fixture
async def open_keys(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    async for client in _app(monkeypatch, ARIA_VISITOR_KEYS="true"):
        yield client


@pytest.fixture
async def no_keys(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[httpx.AsyncClient]:
    async for client in _app(monkeypatch):
        yield client


def _logs() -> list[str]:
    builder = ScenarioBuilder(LinePools.from_loghub(FIXTURES))
    return builder.build("bgl.kernel_panic", seed=8, nodes=4, duration_min=6).lines


def _headers(kind: str = "gemini", key: str = KEY) -> dict[str, str]:
    return {"X-Model-Provider": kind, "X-Model-Key": key}


async def _wait(client: httpx.AsyncClient, run_id: str, *statuses: str) -> dict[str, Any]:
    deadline = time.monotonic() + 60
    while True:
        detail: dict[str, Any] = (await client.get(f"/api/v1/runs/{run_id}")).json()
        if detail["status"] in statuses:
            return detail
        assert time.monotonic() < deadline, f"run {run_id} stayed {detail['status']}"
        await asyncio.sleep(0.05)


def _stored_anywhere(secret: str) -> list[str]:
    """Every table whose rows mention ``secret``, checkpoints and events included."""
    found = []
    with get_engine().connect() as connection:
        for table in Base.metadata.sorted_tables:
            rows = connection.execute(select(table)).fetchall()
            if secret in repr(rows) or secret.encode() in repr(rows).encode():
                found.append(table.name)
    return found


async def test_a_server_that_takes_no_keys_says_so_without_repeating_the_key(
    no_keys: httpx.AsyncClient,
) -> None:
    settings = (await no_keys.get("/api/v1/settings")).json()
    assert settings["visitor_keys"] == []
    body = {"system": "bgl", "logs": _logs()}
    refused = await no_keys.post("/api/v1/runs", json=body, headers=_headers())
    assert refused.status_code == 422
    assert "ARIA_VISITOR_KEYS" in refused.text
    assert KEY not in refused.text
    assert _stored_anywhere(KEY) == []


async def test_a_bad_key_or_provider_is_refused_without_repeating_it(
    open_keys: httpx.AsyncClient,
) -> None:
    body = {"system": "bgl", "logs": _logs()}
    for headers in (
        _headers(kind="mistral"),
        _headers(kind=""),
        {"X-Model-Provider": "gemini", "X-Model-Key": "AIza short"},
    ):
        refused = await open_keys.post("/api/v1/runs", json=body, headers=headers)
        assert refused.status_code == 422, refused.text
        assert "AIza" not in refused.text
    assert (await open_keys.get("/api/v1/runs")).json()["runs"] == []


@respx.mock
async def test_a_visitors_key_answers_their_run_and_is_stored_nowhere(
    open_keys: httpx.AsyncClient, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.route(host="testserver").pass_through()
    google = respx.post(f"{GEMINI}/chat/completions").mock(
        return_value=httpx.Response(503, json={"error": {"message": f"busy, key {KEY}"}})
    )
    settings = (await open_keys.get("/api/v1/settings")).json()
    assert settings["visitor_keys"] == ["claude", "gemini", "openai", "nvidia"]
    created = await open_keys.post(
        "/api/v1/runs", json={"system": "bgl", "logs": _logs()}, headers=_headers()
    )
    assert created.status_code == 202, created.text
    run_id = created.json()["run_id"]
    await _wait(open_keys, run_id, "awaiting_review")
    # Google was asked with the visitor's key; when it failed, the run fell back and finished.
    assert google.called
    assert all(c.request.headers["authorization"] == f"Bearer {KEY}" for c in google.calls)
    events = (await open_keys.get(f"/api/v1/runs/{run_id}/events")).json()
    calls = [e for e in events if e["kind"] == "llm_call"]
    assert any("gemini" in json.dumps(e["payload"]) for e in calls)
    assert KEY not in json.dumps(events)
    assert _stored_anywhere(KEY) == []
    state = open_keys.app.state.aria  # type: ignore[attr-defined]
    assert len(state.runner.keys) == 0
    assert all(s.last_error is None for s in state.services.router.status())
    out, err = capsys.readouterr()
    assert KEY not in out + err


@respx.mock
async def test_the_key_check_says_what_the_provider_said(open_keys: httpx.AsyncClient) -> None:
    respx.route(host="testserver").pass_through()
    catalog = {"object": "list", "data": [{"id": "models/gemini-3.6-flash"}]}
    respx.get(f"{GEMINI}/models").mock(return_value=httpx.Response(200, json=catalog))
    good = await open_keys.post("/api/v1/model-key/check", headers=_headers())
    assert good.json() == {
        "provider": "gemini",
        "accepted": True,
        "model": "gemini-3.6-flash",
        "detail": "Google accepted the key. Runs you start will use gemini-3.6-flash first.",
    }
    respx.get(f"{GEMINI}/models").mock(
        return_value=httpx.Response(400, json={"error": {"message": f"bad key {KEY}"}})
    )
    bad = (await open_keys.post("/api/v1/model-key/check", headers=_headers())).json()
    assert bad["accepted"] is False
    assert "did not accept" in bad["detail"]
    assert KEY not in json.dumps(bad)
    missing = await open_keys.post("/api/v1/model-key/check")
    assert missing.status_code == 422


@respx.mock
async def test_an_nvidia_key_is_checked_with_one_tiny_request(
    open_keys: httpx.AsyncClient,
) -> None:
    respx.route(host="testserver").pass_through()
    nvidia = "https://integrate.api.nvidia.com/v1"
    models = respx.get(f"{nvidia}/models").mock(return_value=httpx.Response(200, json={}))
    chat = respx.post(f"{nvidia}/chat/completions").mock(
        return_value=httpx.Response(401, json={"detail": "Authentication failed"})
    )
    checked = await open_keys.post(
        "/api/v1/model-key/check", headers=_headers("nvidia", "nvapi-" + "v" * 30)
    )
    assert checked.json()["accepted"] is False
    assert chat.called
    assert not models.called


@respx.mock
async def test_ask_aria_answers_with_the_visitors_key(open_keys: httpx.AsyncClient) -> None:
    respx.route(host="testserver").pass_through()
    google = respx.post(f"{GEMINI}/chat/completions").mock(return_value=httpx.Response(503))
    asked = await open_keys.post(
        "/api/v1/ask", json={"question": "Have we seen kernel panics?"}, headers=_headers()
    )
    assert asked.status_code == 200, asked.text
    assert all(c.request.headers["authorization"] == f"Bearer {KEY}" for c in google.calls)


async def test_a_separate_worker_process_means_no_visitor_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async for client in _app(monkeypatch, ARIA_VISITOR_KEYS="true", ARIA_WORKER_MODE="external"):
        assert (await client.get("/api/v1/settings")).json()["visitor_keys"] == []
        refused = await client.post(
            "/api/v1/runs", json={"system": "bgl", "logs": _logs()}, headers=_headers()
        )
        assert refused.status_code == 422


def test_the_shared_allowance_counts_each_visitor_and_the_whole_site_per_day() -> None:
    from aria.config import SharedAllowanceConfig
    from aria.llm.allowance import SharedAllowance

    day = ["2026-10-31"]
    allowance = SharedAllowance(
        SharedAllowanceConfig(per_visitor=2, per_day=3), today=lambda: day[0]
    )
    assert allowance.check("a").left == 2
    assert allowance.take("a")
    assert allowance.take("a")
    assert not allowance.take("a")  # this visitor's two are used
    assert allowance.check("a").left == 0
    assert allowance.take("b")  # the site's third
    assert not allowance.take("c")  # the site's three are used, though c has used none
    assert allowance.check("c").left == 0
    day[0] = "2026-11-01"  # a new UTC day starts afresh
    assert allowance.check("a").left == 2
    assert allowance.take("c")
    unlimited = SharedAllowance(SharedAllowanceConfig())
    assert not unlimited.limited
    assert unlimited.check("a").left is None
    assert all(unlimited.take("a") for _ in range(50))


def test_only_the_sites_own_key_counts_against_the_allowance() -> None:
    from types import SimpleNamespace
    from typing import cast

    from aria.api.keys import may_use_model
    from aria.api.state import AppState
    from aria.config import SharedAllowanceConfig
    from aria.llm.allowance import SharedAllowance
    from aria.llm.visitor import VisitorKey

    def state(real_llm: bool) -> AppState:
        router = SimpleNamespace(has_real_llm=lambda role: real_llm)
        return cast(
            "AppState",
            SimpleNamespace(
                allowance=SharedAllowance(SharedAllowanceConfig(per_visitor=1)),
                services=SimpleNamespace(router=router),
            ),
        )

    shared = state(real_llm=True)
    own = VisitorKey("gemini", SecretStr("x" * 24))
    assert may_use_model(shared, own, "v-1", wanted=True)  # a visitor's own key never counts
    assert not may_use_model(shared, None, "v-1", wanted=False)  # no model wanted: none used
    assert may_use_model(shared, None, "v-1", wanted=True)  # the one the visitor has today
    assert not may_use_model(shared, None, "v-1", wanted=True)  # past it: offline
    assert may_use_model(shared, None, "v-2", wanted=True)  # another visitor has their own
    offline_server = state(real_llm=False)
    for _ in range(3):  # a server without a model of its own counts nothing
        assert may_use_model(offline_server, None, "v-1", wanted=True)
    assert offline_server.allowance.check("v-1").left == 1
