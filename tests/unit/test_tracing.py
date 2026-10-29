"""GenAI semantic-convention spans for LLM calls, tools and agents."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from pydantic import BaseModel

from aria.config import LLMConfig, ProviderConfig, ProviderKind
from aria.llm.base import Message
from aria.llm.fake import FakeProvider
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


async def test_content_capture_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARIA_OTEL_CAPTURE_CONTENT", "true")
    config = LLMConfig(
        providers={"fake": ProviderConfig(kind=ProviderKind.FAKE)}, routing={"default": ["fake"]}
    )
    router = LLMRouter(config, providers={"fake": FakeProvider(script={"t": ['{"ok": true}']})})
    await router.structured("default", "t", [Message("user", "x")], Out)
    (span,) = _EXPORTER.get_finished_spans()
    assert span.attributes is not None
    assert span.attributes["gen_ai.output.text"] == '{"ok": true}'


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
