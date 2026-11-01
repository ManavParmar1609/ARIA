"""Claude, through Anthropic's own SDK and its Messages API.

ARIA's other providers speak the OpenAI chat-completions format. Claude gets its own client so the
requests take the shape Anthropic documents: the system prompt apart from the turns, JSON that
matches a schema through ``output_config.format``, reasoning depth through
``output_config.effort`` (current Claude models always think a little, and the thinking counts
against ``max_tokens``), and no temperature, which current models refuse.

The client is made only once there is a key, and always with that key named explicitly, so the
SDK never falls back to credentials it finds in the environment or a login profile: a visitor's
key is the only credential that goes with a visitor's request.

As with ARIA's other client, each ``chat`` sends one request: the SDK's own retries are off, since
the router's fallback to the next provider is ARIA's one retry layer and every request must be
counted against the limits first. A 429 with ``retry-after`` is a rate limit; one without, or a
message saying when access returns, is the organisation's spend limit, which holds until then
(aria.llm.ratelimit). A refusal (``stop_reason == "refusal"``) raises ``ModelRefusalError`` and
is never repaired on Claude. JSON cut short (``max_tokens`` or
``model_context_window_exceeded``) raises ``OutputTruncatedError`` and is never parsed; text cut
short is returned with ``finish_reason == "length"``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from typing import Any

import anthropic
from pydantic import SecretStr

from aria.config import ProviderConfig, ProviderKind, StructuredOutputMode
from aria.llm.base import (
    Message,
    ProviderError,
    TokenCallback,
    Usage,
    check_stop,
    finish_reason,
)
from aria.llm.ratelimit import classify, retry_after_seconds

_RETRYABLE = frozenset({408, 409, 429})


class ClaudeProvider:
    def __init__(
        self,
        name: str,
        config: ProviderConfig,
        *,
        api_key: SecretStr | None = None,
        http_client: Any = None,
    ) -> None:
        self.name = name
        self.config = config
        self.kind: ProviderKind = ProviderKind.ANTHROPIC
        self.model = config.chat_model or ""
        self.mode = config.structured_output
        self._api_key = api_key if api_key is not None else config.api_key()
        self._http_client = http_client
        self._client: anthropic.AsyncAnthropic | None = None

    def _sdk(self) -> anthropic.AsyncAnthropic:
        if self._api_key is None:
            names = " or ".join(self.config.api_key_names()) or "a key"
            msg = f"{self.name}: no API key: set {names}"
            raise ProviderError(msg)
        if self._client is None:
            stall = self.config.stall_timeout_s or self.config.timeout_s
            self._client = anthropic.AsyncAnthropic(
                api_key=self._api_key.get_secret_value(),
                base_url=self.config.base_url,
                max_retries=0,  # the router's fallback is the one retry layer
                # The read timeout bounds the gap between streamed chunks: a stalled model fails
                # fast and the router moves on.
                timeout=anthropic.Timeout(self.config.timeout_s, connect=15.0, read=stall),
                http_client=self._http_client,
            )
        return self._client

    def _scrub(self, text: str) -> str:
        secret = self._api_key.get_secret_value() if self._api_key is not None else ""
        return text.replace(secret, "[key]") if secret else text

    def _error(self, exc: Exception) -> ProviderError:
        """The SDK's error as the router's: what failed, whether to retry, how long to wait."""
        if isinstance(exc, anthropic.APITimeoutError):
            return ProviderError(self._scrub(f"{self.name}: timed out: {exc}"), timed_out=True)
        if isinstance(exc, anthropic.APIConnectionError):
            return ProviderError(self._scrub(f"{self.name}: {exc}"), retryable=True)
        if isinstance(exc, anthropic.APIStatusError):
            status = exc.status_code
            body = exc.body if isinstance(exc.body, (dict, list)) else {"message": str(exc.message)}
            raw = self._scrub(json.dumps(body, default=str))
            now = time.time()
            return ProviderError(
                self._scrub(f"{self.name}: HTTP {status}: {str(exc.message)[:500]}"),
                status=status,
                retryable=status in _RETRYABLE or status >= 500,
                retry_after=retry_after_seconds(exc.response.headers, raw, now=now),
                limit=classify(status, raw, exc.response.headers, now=now, anthropic=True),
            )
        return ProviderError(self._scrub(f"{self.name}: {type(exc).__name__}: {exc}"))

    def _cost(self, usage: Usage) -> float | None:
        price_in, price_out = self.config.price_input_per_mtok, self.config.price_output_per_mtok
        if price_in is None or price_out is None:
            return None
        return round(usage.input_tokens * price_in / 1e6 + usage.output_tokens * price_out / 1e6, 6)

    def _params(
        self,
        messages: Sequence[Message],
        *,
        json_schema: dict[str, Any] | None,
        max_tokens: int,
        model: str,
    ) -> dict[str, Any]:
        system = [m.content for m in messages if m.role == "system"]
        turns = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
        output: dict[str, Any] = {}
        if self.config.reasoning_effort:
            output["effort"] = self.config.reasoning_effort
        if json_schema is not None:
            if self.mode is StructuredOutputMode.JSON_SCHEMA:
                output["format"] = {"type": "json_schema", "schema": json_schema}
            else:
                system.append(
                    "Respond with one JSON object that matches this JSON Schema:\n"
                    + json.dumps(json_schema)
                )
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens + self.config.reasoning_tokens,
            "messages": turns,
        }
        if system:
            params["system"] = "\n\n".join(system)
        if output:
            params["output_config"] = output
        if self.config.extra_headers:
            params["extra_headers"] = dict(self.config.extra_headers)
        if self.config.extra_body:
            params["extra_body"] = dict(self.config.extra_body)
        return params

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "output",
        temperature: float = 0.1,  # noqa: ARG002 - current Claude models refuse sampling settings
        max_tokens: int = 1_500,
        on_token: TokenCallback | None = None,
        model: str | None = None,
    ) -> tuple[str, Usage]:
        del schema_name  # the Messages API takes the schema alone
        model = model or self.model
        if not model:
            msg = f"{self.name} has no chat model configured"
            raise ProviderError(msg)
        client = self._sdk()
        started = time.perf_counter()
        params = self._params(messages, json_schema=json_schema, max_tokens=max_tokens, model=model)
        try:
            async with client.messages.stream(**params) as stream:
                async for text in stream.text_stream:
                    if on_token is not None:
                        on_token(text)
                final = await stream.get_final_message()
        except anthropic.BadRequestError as exc:
            error = self._error(exc)
            # A schema Claude cannot constrain to: ask for it in the prompt instead, remember,
            # and let the router send the request again in that form.
            refused = str(exc.message).lower()
            if (
                json_schema is not None
                and error.limit is None
                and self.mode is StructuredOutputMode.JSON_SCHEMA
                and any(word in refused for word in ("schema", "output_config", "format"))
            ):
                self.mode = StructuredOutputMode.PROMPT
                error.resend = True
            raise error from exc
        except anthropic.AnthropicError as exc:
            raise self._error(exc) from exc
        text = "".join(block.text for block in final.content if block.type == "text")
        usage = Usage(
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            # "max_tokens" and "model_context_window_exceeded" both read "length".
            finish_reason=finish_reason(final.stop_reason),
            response_id=final.id or None,
            response_model=str(final.model or "") or None,
        )
        usage.cost_usd = self._cost(usage)
        refusal = ""
        if final.stop_reason == "refusal":
            details = getattr(final, "stop_details", None)
            refusal = str(getattr(details, "category", None) or "unspecified")
        # A refusal, or JSON cut short, raises a typed error that carries what it cost.
        check_stop(self.name, usage, structured=json_schema is not None, refusal=refusal)
        return text, usage

    async def list_models(self) -> list[str]:
        """The models this key may use: Anthropic's catalog, which costs no tokens to read."""
        try:
            return sorted([model.id async for model in self._sdk().models.list(limit=100)])
        except anthropic.AnthropicError as exc:
            raise self._error(exc) from exc

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
