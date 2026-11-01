"""Contract tests for the OpenAI-compatible client against mocked HTTP (no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from aria.config import ProviderConfig, ProviderKind, StructuredOutputMode
from aria.llm.base import Message, ProviderError
from aria.llm.openai_compat import OpenAICompatibleProvider

NIM = "https://integrate.api.nvidia.com/v1"
SCHEMA = {
    "type": "object",
    "properties": {"x": {"type": "integer"}},
    "required": ["x"],
    "additionalProperties": False,
}
MESSAGES = [Message("system", "be terse"), Message("user", "give x")]


def _completion(content: str, prompt: int = 11, completion: int = 3) -> dict[str, Any]:
    return {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }


@pytest.fixture
def nim(monkeypatch: pytest.MonkeyPatch) -> OpenAICompatibleProvider:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    cfg = ProviderConfig(
        kind=ProviderKind.NVIDIA_NIM,
        base_url=NIM,
        api_key_env="NVIDIA_API_KEY",
        chat_model="nvidia/test-chat",
        embedding_model="nvidia/test-embed",
        rerank_model="nvidia/test-rerank",
        rerank_url="https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking",
    )
    return OpenAICompatibleProvider("nim", cfg)


@respx.mock
async def test_nim_chat_sends_bearer_key_and_strict_schema(nim: OpenAICompatibleProvider) -> None:
    route = respx.post(f"{NIM}/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion('{"x": 1}'))
    )
    text, usage = await nim.chat(MESSAGES, json_schema=SCHEMA, schema_name="thing")
    assert text == '{"x": 1}'
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer nvapi-test-key"
    body = json.loads(request.content)
    assert body["model"] == "nvidia/test-chat"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"] == {
        "name": "thing",
        "schema": SCHEMA,
        "strict": True,
    }
    assert (usage.input_tokens, usage.output_tokens, usage.estimated) == (11, 3, False)
    assert usage.cost_usd is None  # no price configured


@respx.mock
async def test_azure_v1_uses_api_key_header_and_v1_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "az-secret")
    cfg = ProviderConfig(
        kind=ProviderKind.AZURE_OPENAI,
        base_url="https://res.openai.azure.com",
        api_key_env="AZURE_OPENAI_API_KEY",
        chat_model="gpt-deploy",
        price_input_per_mtok=1.0,
        price_output_per_mtok=4.0,
    )
    route = respx.post("https://res.openai.azure.com/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion("hi", 1_000, 500))
    )
    _, usage = await OpenAICompatibleProvider("azure", cfg).chat(MESSAGES)
    headers = route.calls.last.request.headers
    assert headers["api-key"] == "az-secret"
    assert "authorization" not in headers
    assert usage.cost_usd == pytest.approx(0.003)


@respx.mock
async def test_azure_classic_api_uses_deployment_path() -> None:
    cfg = ProviderConfig(
        kind=ProviderKind.AZURE_OPENAI,
        base_url="https://res.openai.azure.com/",
        allow_no_key=True,
        api_version="2024-10-21",
        chat_model="dep1",
    )
    url = "https://res.openai.azure.com/openai/deployments/dep1/chat/completions"
    route = respx.post(url, params={"api-version": "2024-10-21"}).mock(
        return_value=httpx.Response(200, json=_completion("ok"))
    )
    await OpenAICompatibleProvider("azure", cfg).chat(MESSAGES)
    assert route.called


@respx.mock
async def test_openai_compatible_without_key_sends_no_auth() -> None:
    cfg = ProviderConfig(
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url="http://localhost:11434/v1",
        allow_no_key=True,
        chat_model="llama",
        extra_body={"top_p": 0.9},
    )
    route = respx.post("http://localhost:11434/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "yo"}}]})
    )
    text, usage = await OpenAICompatibleProvider("local", cfg).chat(MESSAGES)
    assert text == "yo"
    assert "authorization" not in route.calls.last.request.headers
    assert json.loads(route.calls.last.request.content)["top_p"] == 0.9
    assert usage.estimated  # no usage block, so tokens are estimated


@respx.mock
async def test_schema_rejection_steps_down_and_is_remembered(nim: OpenAICompatibleProvider) -> None:
    """The client sends one request per call: a rejected way of asking for JSON makes it step
    down and say the request may be sent again, which the router does (and counts)."""
    route = respx.post(f"{NIM}/chat/completions").mock(
        side_effect=[
            httpx.Response(400, json={"error": "response_format not supported"}),
            httpx.Response(200, json=_completion('{"x": 2}')),
            httpx.Response(200, json=_completion('{"x": 3}')),
        ]
    )
    with pytest.raises(ProviderError) as info:
        await nim.chat(MESSAGES, json_schema=SCHEMA)
    assert info.value.resend
    assert route.call_count == 1
    assert nim.mode is StructuredOutputMode.GUIDED_JSON
    text, _ = await nim.chat(MESSAGES, json_schema=SCHEMA)
    assert text == '{"x": 2}'
    second = json.loads(route.calls[1].request.content)
    assert "response_format" not in second
    assert second["nvext"] == {"guided_json": SCHEMA}
    await nim.chat(MESSAGES, json_schema=SCHEMA)
    assert "nvext" in json.loads(route.calls[2].request.content)


@respx.mock
async def test_a_bad_request_that_is_not_about_json_does_not_step_down(
    nim: OpenAICompatibleProvider,
) -> None:
    """A 400 for another reason (a model that refuses the system role, say) is a plain failure:
    stepping down would send the same doomed request three more times."""
    route = respx.post(f"{NIM}/chat/completions").mock(
        return_value=httpx.Response(
            400, json={"error": {"message": "Developer instruction is not enabled for this model"}}
        )
    )
    with pytest.raises(ProviderError) as info:
        await nim.chat(MESSAGES, json_schema=SCHEMA)
    assert not info.value.resend
    assert nim.mode is StructuredOutputMode.JSON_SCHEMA
    assert route.call_count == 1


@respx.mock
async def test_system_messages_can_be_folded_into_the_first_user_message() -> None:
    cfg = ProviderConfig(
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url="http://h/v1",
        allow_no_key=True,
        chat_model="gemma",
        structured_output=StructuredOutputMode.PROMPT,
        system_messages="merge",
    )
    route = respx.post("http://h/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion("{}"))
    )
    await OpenAICompatibleProvider("gemma", cfg).chat(MESSAGES, json_schema=SCHEMA)
    sent = json.loads(route.calls.last.request.content)["messages"]
    assert [m["role"] for m in sent] == ["user"]
    assert sent[0]["content"].startswith("be terse")
    assert '"additionalProperties": false' in sent[0]["content"]  # the schema, in the prompt
    assert sent[0]["content"].endswith("give x")


@respx.mock
async def test_prompt_mode_puts_schema_in_a_system_message() -> None:
    cfg = ProviderConfig(
        kind=ProviderKind.OPENAI_COMPATIBLE,
        base_url="http://h/v1",
        allow_no_key=True,
        chat_model="m",
        structured_output=StructuredOutputMode.PROMPT,
    )
    route = respx.post("http://h/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_completion("{}"))
    )
    await OpenAICompatibleProvider("p", cfg).chat(MESSAGES, json_schema=SCHEMA)
    body = json.loads(route.calls.last.request.content)
    assert "response_format" not in body
    assert body["messages"][-1]["role"] == "system"
    assert '"additionalProperties": false' in body["messages"][-1]["content"]


@respx.mock
async def test_a_rate_limit_is_not_retried_inside_the_client(nim: OpenAICompatibleProvider) -> None:
    """One layer retries provider calls, the router's fallback: the client sends once."""
    route = respx.post(f"{NIM}/chat/completions").mock(
        side_effect=[
            httpx.Response(429, json={"error": "slow down"}),
            httpx.Response(200, json=_completion("done")),
        ]
    )
    with pytest.raises(ProviderError) as info:
        await nim.chat(MESSAGES)
    assert info.value.status == 429
    assert info.value.limit is not None
    assert info.value.limit.kind == "minute"
    assert route.call_count == 1


@respx.mock
async def test_a_retry_after_is_read_and_handed_on(nim: OpenAICompatibleProvider) -> None:
    route = respx.post(f"{NIM}/chat/completions").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "120"}, json={"error": "quota"})
    )
    with pytest.raises(ProviderError) as info:
        await nim.chat(MESSAGES)
    assert info.value.retry_after == 120
    assert info.value.limit is not None
    assert info.value.limit.retry_after == 120
    assert route.call_count == 1  # no retry into the same limit


@respx.mock
async def test_gemini_retry_info_counts_as_retry_after(nim: OpenAICompatibleProvider) -> None:
    body = [
        {
            "error": {
                "code": 429,
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "41s"}
                ],
            }
        }
    ]
    respx.post(f"{NIM}/chat/completions").mock(return_value=httpx.Response(429, json=body))
    with pytest.raises(ProviderError) as info:
        await nim.chat(MESSAGES)
    assert info.value.retry_after == 41.0


@respx.mock
async def test_auth_failure_is_not_retried(nim: OpenAICompatibleProvider) -> None:
    route = respx.post(f"{NIM}/chat/completions").mock(
        return_value=httpx.Response(401, json={"error": "bad key"})
    )
    with pytest.raises(ProviderError) as info:
        await nim.chat(MESSAGES)
    assert info.value.status == 401
    assert not info.value.retryable
    assert route.call_count == 1
    assert "nvapi-test-key" not in str(info.value)


@respx.mock
async def test_transport_errors_are_retryable(nim: OpenAICompatibleProvider) -> None:
    respx.post(f"{NIM}/chat/completions").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(ProviderError) as info:
        await nim.chat(MESSAGES)
    assert info.value.retryable


@respx.mock
async def test_streaming_forwards_tokens_and_reads_final_usage(
    nim: OpenAICompatibleProvider,
) -> None:
    chunks = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"content": '{"x"'}}]},
        {"choices": [{"delta": {"content": ": 7}"}}]},
        {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 4}},
    ]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    route = respx.post(f"{NIM}/chat/completions").mock(
        return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    )
    tokens: list[str] = []
    text, usage = await nim.chat(MESSAGES, on_token=tokens.append)
    assert text == '{"x": 7}'
    assert tokens == ['{"x"', ": 7}"]
    assert (usage.input_tokens, usage.output_tokens) == (20, 4)
    sent = json.loads(route.calls.last.request.content)
    assert sent["stream"] is True
    assert sent["stream_options"] == {"include_usage": True}
    assert route.calls.last.request.headers["accept"] == "text/event-stream"


@respx.mock
async def test_nim_embeddings_send_input_type(nim: OpenAICompatibleProvider) -> None:
    route = respx.post(f"{NIM}/embeddings").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0]},
                    {"index": 0, "embedding": [1.0, 0.0]},
                ]
            },
        )
    )
    vectors = await nim.embed(["a", "b"], input_type="query")
    assert vectors == [[1.0, 0.0], [0.0, 1.0]]  # reordered by index
    body = json.loads(route.calls.last.request.content)
    assert body["input_type"] == "query"
    assert body["truncate"] == "END"
    assert body["model"] == "nvidia/test-embed"


@respx.mock
async def test_azure_embeddings_omit_nim_fields() -> None:
    cfg = ProviderConfig(
        kind=ProviderKind.AZURE_OPENAI,
        base_url="https://res.openai.azure.com",
        allow_no_key=True,
        embedding_model="embed-dep",
    )
    route = respx.post("https://res.openai.azure.com/openai/v1/embeddings").mock(
        return_value=httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5]}]})
    )
    await OpenAICompatibleProvider("azure", cfg).embed(["a"], input_type="passage")
    body = json.loads(route.calls.last.request.content)
    assert "input_type" not in body
    assert body["model"] == "embed-dep"


@respx.mock
async def test_nim_rerank_maps_scores_by_index(nim: OpenAICompatibleProvider) -> None:
    route = respx.post("https://ai.api.nvidia.com/v1/retrieval/nvidia/reranking").mock(
        return_value=httpx.Response(
            200, json={"rankings": [{"index": 2, "logit": 3.5}, {"index": 0, "logit": -1.0}]}
        )
    )
    scores = await nim.rerank("disk full", ["p0", "p1", "p2"])
    assert scores == [-1.0, 0.0, 3.5]
    body = json.loads(route.calls.last.request.content)
    assert body["query"] == {"text": "disk full"}
    assert body["passages"] == [{"text": "p0"}, {"text": "p1"}, {"text": "p2"}]


@respx.mock
async def test_list_models_reads_catalog(nim: OpenAICompatibleProvider) -> None:
    respx.get(f"{NIM}/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "b"}, {"id": "a"}]})
    )
    assert await nim.list_models() == ["a", "b"]


async def test_missing_models_raise_clear_errors() -> None:
    cfg = ProviderConfig(
        kind=ProviderKind.OPENAI_COMPATIBLE, base_url="http://h/v1", allow_no_key=True
    )
    provider = OpenAICompatibleProvider("p", cfg)
    with pytest.raises(ProviderError, match="no chat model"):
        await provider.chat(MESSAGES)
    with pytest.raises(ProviderError, match="no embedding_model"):
        await provider.embed(["x"])
    with pytest.raises(ProviderError, match="no reranker"):
        await provider.rerank("q", ["p"])
    with pytest.raises(ValueError, match="no base_url"):
        OpenAICompatibleProvider("x", ProviderConfig(kind=ProviderKind.NVIDIA_NIM))


@respx.mock
async def test_reasoning_effort_and_stream_always_are_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    cfg = ProviderConfig(
        kind=ProviderKind.NVIDIA_NIM,
        base_url=NIM,
        api_key_env="NVIDIA_API_KEY",
        chat_model="openai/gpt-oss-20b",
        reasoning_effort="low",
        stream_always=True,
        stall_timeout_s=5,
    )
    body = 'data: {"choices": [{"delta": {"content": "OK"}}]}\n\ndata: [DONE]\n\n'
    route = respx.post(f"{NIM}/chat/completions").mock(
        return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    )
    text, _ = await OpenAICompatibleProvider("nim", cfg).chat(MESSAGES)  # no on_token callback
    sent = json.loads(route.calls.last.request.content)
    assert text == "OK"
    assert sent["stream"] is True
    assert sent["reasoning_effort"] == "low"
    assert route.calls.last.request.extensions["timeout"]["read"] == 5


@respx.mock
async def test_a_stalled_stream_fails_over_without_retrying(nim: OpenAICompatibleProvider) -> None:
    nim.config = nim.config.model_copy(update={"stream_always": True})
    route = respx.post(f"{NIM}/chat/completions").mock(side_effect=httpx.ReadTimeout("no bytes"))
    with pytest.raises(ProviderError) as info:
        await nim.chat(MESSAGES)
    assert info.value.timed_out
    assert not info.value.retryable
    assert route.call_count == 1  # a slow provider is not asked again; the router moves on


@respx.mock
async def test_a_broken_connection_is_not_retried_inside_the_client(
    nim: OpenAICompatibleProvider,
) -> None:
    route = respx.post(f"{NIM}/chat/completions").mock(
        side_effect=[httpx.ConnectError("reset"), httpx.Response(200, json=_completion("{}"))]
    )
    with pytest.raises(ProviderError) as info:
        await nim.chat(MESSAGES)
    assert info.value.retryable  # another provider may answer: the router moves on
    assert route.call_count == 1


@respx.mock
async def test_a_reply_that_breaks_off_is_a_provider_error_not_a_crash(
    nim: OpenAICompatibleProvider,
) -> None:
    """Malformed replies become provider errors the router can fail over from, never an
    exception that would fail the run's step or set off the graph's node retry."""
    respx.post(f"{NIM}/chat/completions").mock(
        side_effect=[
            httpx.Response(200, text="<html>gateway</html>"),
            httpx.Response(
                200, text="data: {not json\n\n", headers={"content-type": "text/event-stream"}
            ),
        ]
    )
    with pytest.raises(ProviderError, match="not JSON"):
        await nim.chat(MESSAGES)
    with pytest.raises(ProviderError, match="not JSON"):
        await nim.chat(MESSAGES, on_token=lambda _: None)


@respx.mock
async def test_finish_reasons_and_refusals_are_reported(nim: OpenAICompatibleProvider) -> None:
    def completion(content: str, finish: str, refusal: str | None = None) -> dict[str, Any]:
        message: dict[str, Any] = {"role": "assistant", "content": content}
        if refusal:
            message["refusal"] = refusal
        return {
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 9},
        }

    respx.post(f"{NIM}/chat/completions").mock(
        side_effect=[
            httpx.Response(200, json=completion('{"x": ', "length")),
            httpx.Response(200, json=completion("", "stop", refusal="I can't help with that.")),
            httpx.Response(200, json=completion("", "content_filter")),
            httpx.Response(200, json=completion('{"x": 1}', "stop")),
        ]
    )
    _, usage = await nim.chat(MESSAGES)
    assert usage.finish_reason == "length"
    for _ in range(2):
        with pytest.raises(ProviderError) as info:
            await nim.chat(MESSAGES)
        assert info.value.refused
    _, usage = await nim.chat(MESSAGES)
    assert usage.finish_reason == "stop"


@respx.mock
async def test_a_streamed_finish_reason_is_read(nim: OpenAICompatibleProvider) -> None:
    chunks = [
        {"choices": [{"delta": {"content": '{"x"'}}]},
        {"choices": [{"delta": {}, "finish_reason": "length"}]},
    ]
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    respx.post(f"{NIM}/chat/completions").mock(
        return_value=httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
    )
    text, usage = await nim.chat(MESSAGES, on_token=lambda _: None)
    assert (text, usage.finish_reason) == ('{"x"', "length")


def test_blank_env_values_mean_not_configured() -> None:
    cfg = ProviderConfig(
        kind=ProviderKind.NVIDIA_NIM, base_url=" ", rerank_model="", reasoning_effort=""
    )
    assert (cfg.base_url, cfg.rerank_model, cfg.reasoning_effort) == (None, None, None)
    assert not cfg.is_enabled()
