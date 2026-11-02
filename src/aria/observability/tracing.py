"""OpenTelemetry tracing and metrics with the GenAI semantic conventions.

Spans follow the OpenTelemetry GenAI conventions (``gen_ai.*`` attributes, span names such as
``chat <model>`` and ``execute_tool <tool>``), so any OTLP backend (Langfuse, Arize Phoenix,
Jaeger) or Azure Monitor can show agent runs. Every model call records, on its span:

* ``gen_ai.provider.name``, ``gen_ai.operation.name`` and ``gen_ai.request.model``;
* ``gen_ai.response.model`` and ``gen_ai.response.id``, as the provider reported them;
* ``gen_ai.response.finish_reasons`` and ``gen_ai.usage.input_tokens`` and
  ``gen_ai.usage.output_tokens``, also for a reply that was declined or cut short;
* ``error.type`` when the call failed, and ``server.address`` and ``server.port``;

and two histograms, ``gen_ai.client.token.usage`` (tokens the provider reported, by
``gen_ai.token.type``) and ``gen_ai.client.operation.duration`` (seconds), with the bucket
boundaries the conventions advise. The names are those of the released conventions (v1.37 and
after); the GenAI conventions are still in development, and their newest drafts move inference
metrics to ``gen_ai.client.inference.*``.

Spans and metrics never carry prompt or completion text, keys or error messages (which can
quote either): only identifiers, counts and the class of an error.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any
from urllib.parse import urlsplit

from opentelemetry import metrics, trace
from opentelemetry.metrics import Histogram, MeterProvider
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

from aria.config import ProviderKind

_TRACER_NAME = "aria"
_PROVIDER_NAMES = {
    ProviderKind.NVIDIA_NIM: "nvidia.nim",
    ProviderKind.AZURE_OPENAI: "azure.ai.openai",
    ProviderKind.OPENAI_COMPATIBLE: "openai",
    ProviderKind.ANTHROPIC: "anthropic",
    ProviderKind.FAKE: "aria.fake",
    ProviderKind.LOCAL: "aria.local",
}
# The conventions' well-known provider names, by the API host a client talks to: an
# OpenAI-compatible client talking to Google's Gemini API is Gemini, not OpenAI.
_PROVIDER_HOSTS = (
    ("generativelanguage.googleapis.com", "gcp.gemini"),
    ("aiplatform.googleapis.com", "gcp.vertex_ai"),
    ("api.openai.com", "openai"),
    ("openai.azure.com", "azure.ai.openai"),
    ("api.anthropic.com", "anthropic"),
)
# Bucket boundaries the GenAI metric conventions advise.
TOKEN_BUCKETS = (
    1,
    4,
    16,
    64,
    256,
    1024,
    4096,
    16384,
    65536,
    262144,
    1048576,
    4194304,
    16777216,
    67108864,
)
DURATION_BUCKETS = (
    0.01,
    0.02,
    0.04,
    0.08,
    0.16,
    0.32,
    0.64,
    1.28,
    2.56,
    5.12,
    10.24,
    20.48,
    40.96,
    81.92,
)
_configured = False
_instruments: tuple[MeterProvider, Histogram, Histogram] | None = None


def tracer() -> trace.Tracer:
    return trace.get_tracer(_TRACER_NAME)


def genai_provider_name(kind: ProviderKind, base_url: str | None = None) -> str:
    """``gen_ai.provider.name``: the conventions' well-known name for the API at ``base_url``
    when it is one, else the name for the client's kind (a self-hosted endpoint, NIM)."""
    host = _host(base_url)
    for suffix, name in _PROVIDER_HOSTS:
        if host == suffix or host.endswith(f".{suffix}"):
            return name
    return _PROVIDER_NAMES.get(kind, str(kind))


def _host(url: str | None) -> str:
    try:
        return (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""


def server_attributes(base_url: str | None) -> dict[str, Any]:
    """``server.address`` and ``server.port`` of a provider's endpoint, when it has one. The
    host and port only: never a path or query, which could carry a key."""
    try:
        parts = urlsplit(base_url or "")
        port = parts.port
    except ValueError:
        return {}
    if not parts.hostname:
        return {}
    known = port or {"https": 443, "http": 80}.get(parts.scheme)
    return {"server.address": parts.hostname, **({"server.port": known} if known else {})}


def error_type(exc: BaseException) -> str:
    """``error.type``: a low-cardinality class of the error, never its message. A provider's
    HTTP status when it gave one, else the exception's class."""
    status = getattr(exc, "status", None)
    return str(status) if isinstance(status, int) else type(exc).__name__


@contextmanager
def genai_span(
    operation: str,
    *,
    kind: ProviderKind,
    model: str,
    base_url: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> Iterator[Span]:
    provider = genai_provider_name(kind, base_url)
    attrs: dict[str, Any] = {
        "gen_ai.operation.name": operation,
        "gen_ai.provider.name": provider,
        "gen_ai.system": provider,  # pre-1.37 name, still read by some backends
        "gen_ai.request.model": model,
        **server_attributes(base_url),
    }
    attrs.update({k: v for k, v in (attributes or {}).items() if v is not None})
    with tracer().start_as_current_span(
        f"{operation} {model}", kind=SpanKind.CLIENT, attributes=attrs
    ) as span:
        yield span


def record_response(
    span: Span,
    *,
    response_model: str | None,
    response_id: str | None,
    finish_reasons: Sequence[str],
    input_tokens: int | None,
    output_tokens: int | None,
    estimated: bool = False,
) -> None:
    """What the provider said about its reply, on the call's span. Counts the provider did not
    report are left out, or marked ``aria.usage.estimated`` when ARIA estimated them."""
    if response_model:
        span.set_attribute("gen_ai.response.model", response_model)
    if response_id:
        span.set_attribute("gen_ai.response.id", response_id)
    if finish_reasons:
        span.set_attribute("gen_ai.response.finish_reasons", list(finish_reasons))
    if input_tokens is not None:
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    if output_tokens is not None:
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    if estimated:
        span.set_attribute("aria.usage.estimated", True)


def _meter_provider() -> MeterProvider:
    return metrics.get_meter_provider()


def _histograms() -> tuple[Histogram, Histogram]:
    """The two GenAI client histograms on the current meter provider, made once per provider."""
    global _instruments  # noqa: PLW0603 - instruments belong to the process's meter provider
    provider = _meter_provider()
    if _instruments is None or _instruments[0] is not provider:
        meter = provider.get_meter(_TRACER_NAME)
        tokens = meter.create_histogram(
            "gen_ai.client.token.usage",
            unit="{token}",
            description="Number of input and output tokens used",
            explicit_bucket_boundaries_advisory=TOKEN_BUCKETS,
        )
        duration = meter.create_histogram(
            "gen_ai.client.operation.duration",
            unit="s",
            description="GenAI operation duration",
            explicit_bucket_boundaries_advisory=DURATION_BUCKETS,
        )
        _instruments = (provider, tokens, duration)
    return _instruments[1], _instruments[2]


def record_metrics(
    *,
    operation: str,
    provider: str,
    request_model: str,
    response_model: str | None,
    duration_s: float,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error: str | None = None,
    server: dict[str, Any] | None = None,
) -> None:
    """One model call on the GenAI client histograms. Token counts are recorded only when the
    provider reported them: an estimate is not a measurement."""
    tokens, duration = _histograms()
    attrs: dict[str, Any] = {
        "gen_ai.operation.name": operation,
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": request_model,
        **(server or {}),
    }
    if response_model:
        attrs["gen_ai.response.model"] = response_model
    duration.record(max(0.0, duration_s), {**attrs, **({"error.type": error} if error else {})})
    for token_type, count in (("input", input_tokens), ("output", output_tokens)):
        if count is not None:
            tokens.record(count, {**attrs, "gen_ai.token.type": token_type})


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
    """Mark the span failed with the error's class, never its message: a provider's or a tool's
    error text can quote a prompt, log lines or a reply."""
    kind = error_type(exc)
    span.set_attribute("error.type", kind)
    span.set_status(Status(StatusCode.ERROR, kind))


def configure_tracing(
    exporter: str,
    *,
    service_name: str = "aria",
    endpoint: str | None = None,
    metrics_endpoint: str | None = None,
) -> None:
    """Install a tracer provider once. ``exporter`` is none, console, otlp or azure.

    Metrics go with Azure Monitor's distro on ``azure``; with ``otlp`` they are exported only
    when ``metrics_endpoint`` names where (a traces-only backend such as Phoenix refuses them).
    """
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

    resource = Resource.create({"service.name": service_name})
    span_exporter: SpanExporter
    if exporter == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: PLC0415
            OTLPSpanExporter,
        )

        span_exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
        if metrics_endpoint:
            _configure_metrics(resource, metrics_endpoint)
    else:
        span_exporter = ConsoleSpanExporter()
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(provider)
    _configured = True


def _configure_metrics(resource: Any, endpoint: str) -> None:
    """Export the GenAI histograms over OTLP/HTTP to ``endpoint``."""
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # noqa: PLC0415
        OTLPMetricExporter,
    )
    from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider  # noqa: PLC0415
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader  # noqa: PLC0415

    reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint))
    metrics.set_meter_provider(SdkMeterProvider(resource=resource, metric_readers=[reader]))
