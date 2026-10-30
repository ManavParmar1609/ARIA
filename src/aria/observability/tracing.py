"""OpenTelemetry tracing with the GenAI semantic conventions.

Spans follow the OpenTelemetry GenAI conventions (``gen_ai.*`` attributes, span names such as
``chat <model>`` and ``execute_tool <tool>``), so any OTLP backend (Langfuse, Arize Phoenix,
Jaeger) or Azure Monitor can show agent runs. Prompt and completion text are not recorded
unless ``ARIA_OTEL_CAPTURE_CONTENT=true``, because they can contain log data.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from aria.config import ProviderKind

_TRACER_NAME = "aria"
_PROVIDER_NAMES = {
    ProviderKind.NVIDIA_NIM: "nvidia.nim",
    ProviderKind.AZURE_OPENAI: "azure.ai.openai",
    ProviderKind.OPENAI_COMPATIBLE: "openai",
    ProviderKind.FAKE: "aria.fake",
    ProviderKind.LOCAL: "aria.local",
}
_configured = False


def tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)


def capture_content() -> bool:
    return os.environ.get("ARIA_OTEL_CAPTURE_CONTENT", "").lower() in {"1", "true", "yes"}


def genai_provider_name(kind: ProviderKind) -> str:
    return _PROVIDER_NAMES.get(kind, str(kind))


@contextmanager
def genai_span(
    operation: str,
    *,
    kind: ProviderKind,
    model: str,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Span]:
    provider = genai_provider_name(kind)
    attrs: dict[str, Any] = {
        "gen_ai.operation.name": operation,
        "gen_ai.provider.name": provider,
        "gen_ai.system": provider,  # pre-1.37 name, still read by some backends
        "gen_ai.request.model": model,
    }
    attrs.update({k: v for k, v in (attributes or {}).items() if v is not None})
    with tracer().start_as_current_span(
        f"{operation} {model}", kind=SpanKind.CLIENT, attributes=attrs
    ) as span:
        yield span


@contextmanager
def tool_span(tool: str, *, agent: str, call_id: str) -> Iterator[Span]:
    attrs = {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": tool,
        "gen_ai.tool.call.id": call_id,
        "gen_ai.agent.name": agent,
    }
    with tracer().start_as_current_span(
        f"execute_tool {tool}", kind=SpanKind.INTERNAL, attributes=attrs
    ) as span:
        yield span


@contextmanager
def agent_span(agent: str, *, run_id: str) -> Iterator[Span]:
    attrs = {
        "gen_ai.operation.name": "invoke_agent",
        "gen_ai.agent.name": agent,
        "gen_ai.conversation.id": run_id,
    }
    with tracer().start_as_current_span(
        f"invoke_agent {agent}", kind=SpanKind.INTERNAL, attributes=attrs
    ) as span:
        yield span


def mark_error(span: Span, exc: BaseException) -> None:
    span.set_attribute("error.type", type(exc).__name__)
    span.set_status(Status(StatusCode.ERROR, str(exc)[:200]))


def configure_tracing(
    exporter: str, *, service_name: str = "aria", endpoint: str | None = None
) -> None:
    """Install a tracer provider once. ``exporter`` is none, console, otlp or azure."""
    global _configured  # noqa: PLW0603 - process-wide, idempotent setup
    if _configured or exporter == "none":
        return
    if exporter == "azure":
        from azure.monitor.opentelemetry import configure_azure_monitor  # noqa: PLC0415 - extra

        configure_azure_monitor()
        _configured = True
        return
    from opentelemetry.sdk.resources import Resource  # noqa: PLC0415
    from opentelemetry.sdk.trace import TracerProvider  # noqa: PLC0415
    from opentelemetry.sdk.trace.export import (  # noqa: PLC0415
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SpanExporter,
    )

    span_exporter: SpanExporter
    if exporter == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter,
        )

        span_exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
    else:
        span_exporter = ConsoleSpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(provider)
    _configured = True
