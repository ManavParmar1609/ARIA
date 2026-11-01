"""GenAI semantic-convention spans and metrics for LLM calls, tools and agents."""

from __future__ import annotations

from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel

from aria.config import LLMConfig, ProviderConfig, ProviderKind, get_app_config
from aria.llm.base import LLMError, Message, ModelRefusalError, ProviderError, Usage
from aria.llm.fake import FakeProvider
from aria.llm.quota import QuotaLedger
from aria.llm.router import LLMRouter
from aria.observability import tracing

_EXPORTER = InMemorySpanExporter()


@pytest.fixture(scope="module", autouse=True)
def _provider() -> None:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_EXPORTER))
    trace.set_tracer_provider(provider)


@pytest.fixture(autouse=True)
def _clear() -> None:
    _EXPORTER.clear()


class Out(BaseModel):
    ok: bool


async def test_llm_calls_emit_genai_chat_spans_without_content() -> None:
    config = LLMConfig(
        providers={"fake": ProviderConfig(kind=ProviderKind.FAKE)}, routing={"default": ["fake"]}
    )
    router = LLMRouter(config, providers={"fake": FakeProvider(script={"t": ['{"ok": true}']})})
    await router.structured("default", "t", [Message("user", "secret log line")], Out)
    (span,) = _EXPORTER.get_finished_spans()
    attrs = dict(span.attributes or {})
    assert span.name == "chat aria-fake-1"
    assert attrs["gen_ai.operation.name"] == "chat"
    assert attrs["gen_ai.provider.name"] == "aria.fake"
    assert int(str(attrs["gen_ai.usage.output_tokens"])) > 0
    assert attrs["aria.task"] == "t"
    assert not any("secret" in str(v) for v in attrs.values())


KEY = "AIza-tracing-test-key-0123456789"
PROMPT = "secret log line from host db-7"
REPLY = '{"ok": true, "note": "the model wrote this"}'


class Gemini:
    """A real model (not the offline stand-in) on Google's Gemini API, scripted."""

    kind = ProviderKind.OPENAI_COMPATIBLE

    def __init__(self, *script: Any) -> None:
        self.name, self.model = "gemini", "gemini-3.6-flash"
        self.script = list(script)

    async def chat(self, messages: Any, **kwargs: Any) -> tuple[str, Usage]:
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def metrics_reader(monkeypatch: pytest.MonkeyPatch) -> InMemoryMetricReader:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    monkeypatch.setattr(tracing, "_meter_provider", lambda: provider)
    return reader


def _points(reader: InMemoryMetricReader) -> dict[str, tuple[str, list[Any]]]:
    data = reader.get_metrics_data()
    assert data is not None
    return {
        metric.name: (metric.unit, list(metric.data.data_points))
        for resource in data.resource_metrics
        for scope in resource.scope_metrics
        for metric in scope.metrics
    }


def _gemini_router(model: Gemini) -> LLMRouter:
    config = LLMConfig(
        providers={"gemini": get_app_config().llm.providers["gemini"]},
        routing={"default": ["gemini"]},
    )
    return LLMRouter(config, providers={"gemini": model}, ledger=QuotaLedger({}))


async def test_every_model_call_records_the_genai_attributes_and_histograms(
    metrics_reader: InMemoryMetricReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", KEY)
    usage = Usage(
        input_tokens=120,
        output_tokens=30,
        finish_reason="stop",
        response_id="resp-7f3a",
        response_model="gemini-3.6-flash-001",
    )
    router = _gemini_router(Gemini((REPLY, usage)))
    await router.structured("default", "t", [Message("user", PROMPT)], Out)
    (span,) = _EXPORTER.get_finished_spans()
    attrs = dict(span.attributes or {})
    assert span.name == "chat gemini-3.6-flash"
    assert {k: attrs[k] for k in attrs if k.startswith(("gen_ai.", "server."))} == {
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "gcp.gemini",  # the conventions' name for Google's Gemini API
        "gen_ai.system": "gcp.gemini",
        "gen_ai.request.model": "gemini-3.6-flash",
        "gen_ai.request.temperature": 0.1,
        "gen_ai.request.max_tokens": 1_500,
        "gen_ai.output.type": "json",
        "gen_ai.response.model": "gemini-3.6-flash-001",
        "gen_ai.response.id": "resp-7f3a",
        "gen_ai.response.finish_reasons": ("stop",),
        "gen_ai.usage.input_tokens": 120,
        "gen_ai.usage.output_tokens": 30,
        "server.address": "generativelanguage.googleapis.com",
        "server.port": 443,
    }
    text = " ".join(str(v) for v in attrs.values())
    for private in (PROMPT, "db-7", "the model wrote this", KEY):
        assert private not in text  # no prompt, reply or key, ever

    points = _points(metrics_reader)
    unit, tokens = points["gen_ai.client.token.usage"]
    assert unit == "{token}"
    by_type = {p.attributes["gen_ai.token.type"]: p for p in tokens}
    assert (by_type["input"].sum, by_type["output"].sum) == (120, 30)
    assert tuple(by_type["input"].explicit_bounds) == tracing.TOKEN_BUCKETS
    assert by_type["input"].attributes["gen_ai.provider.name"] == "gcp.gemini"
    assert by_type["input"].attributes["gen_ai.response.model"] == "gemini-3.6-flash-001"
    unit, durations = points["gen_ai.client.operation.duration"]
    assert unit == "s"
    (duration,) = durations
    assert duration.count == 1
    assert tuple(duration.explicit_bounds) == tracing.DURATION_BUCKETS
    assert duration.attributes["gen_ai.operation.name"] == "chat"
    assert duration.attributes["gen_ai.request.model"] == "gemini-3.6-flash"
    assert "error.type" not in duration.attributes


async def test_a_failed_or_declined_call_records_its_error_class_never_its_message(
    metrics_reader: InMemoryMetricReader,
) -> None:
    declined = ModelRefusalError(
        f"gemini: the model declined the request (it quoted: {PROMPT})",
        reason="content_filter",
        usage=Usage(input_tokens=80, output_tokens=0, finish_reason="content_filter"),
    )
    limited = ProviderError(f"gemini: HTTP 429: quota exceeded for {PROMPT}", status=429)
    router = _gemini_router(Gemini(declined, limited))
    for _ in range(2):
        with pytest.raises(LLMError):
            await router.structured("default", "t", [Message("user", PROMPT)], Out)
    refused, rate_limited = _EXPORTER.get_finished_spans()
    attrs = dict(refused.attributes or {})
    assert attrs["error.type"] == "ModelRefusalError"
    assert attrs["gen_ai.response.finish_reasons"] == ("content_filter",)
    assert attrs["gen_ai.usage.input_tokens"] == 80  # a declined reply is still billed
    assert dict(rate_limited.attributes or {})["error.type"] == "429"
    for span in (refused, rate_limited):
        assert span.status.description in ("ModelRefusalError", "429")
        assert PROMPT not in " ".join(str(v) for v in (span.attributes or {}).values())
    _, durations = _points(metrics_reader)["gen_ai.client.operation.duration"]
    assert sorted(p.attributes["error.type"] for p in durations) == ["429", "ModelRefusalError"]


def test_provider_names_follow_the_conventions_by_the_api_a_client_talks_to() -> None:
    names = {
        (ProviderKind.OPENAI_COMPATIBLE, "https://generativelanguage.googleapis.com/v1beta/openai"):
            "gcp.gemini",
        (ProviderKind.OPENAI_COMPATIBLE, "https://api.openai.com/v1"): "openai",
        (ProviderKind.OPENAI_COMPATIBLE, "http://localhost:11434/v1"): "openai",
        (ProviderKind.ANTHROPIC, "https://api.anthropic.com"): "anthropic",
        (ProviderKind.AZURE_OPENAI, "https://res.openai.azure.com"): "azure.ai.openai",
        (ProviderKind.NVIDIA_NIM, "https://integrate.api.nvidia.com/v1"): "nvidia.nim",
        (ProviderKind.FAKE, None): "aria.fake",
    }  # fmt: skip
    for (kind, url), name in names.items():
        assert tracing.genai_provider_name(kind, url) == name, url
    assert tracing.server_attributes("http://nim:8000/v1?key=x") == {
        "server.address": "nim",
        "server.port": 8000,
    }
    assert tracing.server_attributes(None) == {}


def test_tool_and_agent_spans_and_errors() -> None:
    with (
        tracing.agent_span("severity", run_id="run-1"),
        tracing.tool_span("search_logs", agent="investigator", call_id="c1") as span,
    ):
        tracing.mark_error(span, RuntimeError("boom"))
    tool, agent = _EXPORTER.get_finished_spans()
    assert tool.name == "execute_tool search_logs"
    assert tool.attributes is not None
    assert tool.attributes["error.type"] == "RuntimeError"
    assert agent.name == "invoke_agent severity"
    assert agent.attributes is not None
    assert agent.attributes["gen_ai.conversation.id"] == "run-1"
    assert tracing.genai_provider_name(ProviderKind.NVIDIA_NIM) == "nvidia.nim"


def test_configure_tracing_none_is_a_no_op() -> None:
    tracing.configure_tracing("none")
    assert not tracing._configured
