"""One HTTP client for every OpenAI-compatible endpoint: NIM, Azure OpenAI, Gemini, OpenAI, vLLM.

Differences between providers are confined to URL construction, authentication, and how JSON
output is requested. If a provider rejects the configured structured-output mode, the client
steps down (json_schema -> guided_json -> json_object -> prompt) and remembers what worked.
"""

from __future__ import annotations

import asyncio
import email.utils
import json
import re
import time
from collections.abc import Sequence
from typing import Any, Literal

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from aria.config import ProviderConfig, ProviderKind, StructuredOutputMode
from aria.llm.base import Message, ProviderError, TokenCallback, Usage, estimate_tokens

_AZURE_SCOPE = "https://cognitiveservices.azure.com/.default"
_STEP_DOWN = {
    StructuredOutputMode.JSON_SCHEMA: StructuredOutputMode.GUIDED_JSON,
    StructuredOutputMode.GUIDED_JSON: StructuredOutputMode.JSON_OBJECT,
    StructuredOutputMode.JSON_OBJECT: StructuredOutputMode.PROMPT,
}


def _retryable(exc: BaseException) -> bool:
    return isinstance(exc, ProviderError) and exc.retryable


# Longer than this and a retry inside the call would only hit the same limit (tenacity's backoff
# tops out at 8 s), so the router fails over and keeps its breaker open for the wait instead.
_MAX_WAIT_IN_CALL_S = 8.0
_RETRY_DELAY = re.compile(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"')


def _retry_after(response: httpx.Response, body: str) -> float | None:
    """How long the provider asked callers to wait: Retry-After, or Gemini's RetryInfo."""
    header = response.headers.get("retry-after", "").strip()
    if header.replace(".", "", 1).isdigit():
        return float(header)
    if header:
        try:
            when = email.utils.parsedate_to_datetime(header)
        except (TypeError, ValueError):
            when = None
        if when is not None:
            return max(0.0, when.timestamp() - time.time())
    match = _RETRY_DELAY.search(body)
    return float(match.group(1)) if match else None


class OpenAICompatibleProvider:
    def __init__(
        self, name: str, config: ProviderConfig, client: httpx.AsyncClient | None = None
    ) -> None:
        if not config.base_url:
            msg = f"provider {name} has no base_url"
            raise ValueError(msg)
        self.name = name
        self.config = config
        self.kind: ProviderKind = config.kind
        self.model = config.chat_model or ""
        self.mode = config.structured_output
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(config.timeout_s, connect=15.0)
        )
        self._credential: Any = None

    # --- endpoints and auth --------------------------------------------------------------------

    def _url(
        self, operation: Literal["chat/completions", "embeddings", "models"], model: str
    ) -> str:
        base = (self.config.base_url or "").rstrip("/")
        if self.kind is ProviderKind.AZURE_OPENAI:
            if self.config.api_version:  # classic data-plane API
                if operation == "models":
                    return f"{base}/openai/models?api-version={self.config.api_version}"
                return f"{base}/openai/deployments/{model}/{operation}?api-version={self.config.api_version}"
            return f"{base}/openai/v1/{operation}"
        return f"{base}/{operation}"

    async def _headers(self, *, stream: bool = False) -> dict[str, str]:
        accept = "text/event-stream" if stream else "application/json"
        headers = {"Content-Type": "application/json", "Accept": accept}
        if self.kind is ProviderKind.AZURE_OPENAI and self.config.azure_ad:
            if self._credential is None:
                from azure.identity.aio import DefaultAzureCredential  # noqa: PLC0415 - optional extra

                self._credential = DefaultAzureCredential()
            token = await self._credential.get_token(_AZURE_SCOPE)
            headers["Authorization"] = f"Bearer {token.token}"
            return headers
        key = self.config.api_key()
        if key is not None:
            if self.kind is ProviderKind.AZURE_OPENAI:
                headers["api-key"] = key.get_secret_value()
            else:
                headers["Authorization"] = f"Bearer {key.get_secret_value()}"
        return headers

    def _cost(self, usage: Usage) -> float | None:
        price_in, price_out = self.config.price_input_per_mtok, self.config.price_output_per_mtok
        if price_in is None or price_out is None:
            return None
        return round(usage.input_tokens * price_in / 1e6 + usage.output_tokens * price_out / 1e6, 6)

    async def _post(self, url: str, payload: dict[str, Any], *, stream: bool) -> httpx.Response:
        headers = await self._headers(stream=stream)
        timeout = httpx.Timeout(
            self.config.timeout_s,
            connect=15.0,
            # While streaming, the read timeout bounds the gap between chunks: a stalled model
            # fails fast and the router moves on.
            read=(self.config.stall_timeout_s or self.config.timeout_s)
            if stream
            else self.config.timeout_s,
        )
        request = self._client.build_request(
            "POST", url, json=payload, headers=headers, timeout=timeout
        )
        try:
            response = await self._client.send(request, stream=stream)
        except httpx.TimeoutException as exc:
            # A provider that is too slow now will likely stay slow for the next attempt too,
            # so the router fails over at once instead of retrying here.
            raise ProviderError(
                f"{self.name}: {type(exc).__name__}: {exc}", timed_out=True
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(
                f"{self.name}: {type(exc).__name__}: {exc}", retryable=True
            ) from exc
        if response.status_code >= 400:
            raw = (await response.aread()).decode(errors="replace")
            await response.aclose()
            wait = _retry_after(response, raw)
            retryable = response.status_code in (408, 409, 429) or response.status_code >= 500
            if wait is not None and wait > _MAX_WAIT_IN_CALL_S:
                retryable = False
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code}: {raw[:500]}",
                status=response.status_code,
                retryable=retryable,
                retry_after=wait,
            )
        return response

    # --- chat ----------------------------------------------------------------------------------

    def _payload(
        self,
        messages: Sequence[Message],
        *,
        json_schema: dict[str, Any] | None,
        schema_name: str,
        temperature: float,
        max_tokens: int,
        stream: bool,
        mode: StructuredOutputMode,
        model: str,
    ) -> dict[str, Any]:
        msgs = [m.as_dict() for m in messages]
        payload: dict[str, Any] = {
            "model": model,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if stream:
            payload["stream_options"] = {"include_usage": True}
        if self.config.reasoning_effort:
            payload["reasoning_effort"] = self.config.reasoning_effort
        if json_schema is not None:
            if mode is StructuredOutputMode.JSON_SCHEMA:
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "schema": json_schema, "strict": True},
                }
            elif mode is StructuredOutputMode.GUIDED_JSON:
                payload["nvext"] = {"guided_json": json_schema}
            elif mode is StructuredOutputMode.JSON_OBJECT:
                payload["response_format"] = {"type": "json_object"}
            if mode in (StructuredOutputMode.JSON_OBJECT, StructuredOutputMode.PROMPT):
                hint = "Respond with one JSON object that matches this JSON Schema:\n" + json.dumps(
                    json_schema
                )
                msgs.append({"role": "system", "content": hint})
        payload.update(self.config.extra_body)
        return payload

    async def _read_stream(
        self, response: httpx.Response, on_token: TokenCallback | None
    ) -> tuple[str, dict[str, Any] | None]:
        parts: list[str] = []
        usage: dict[str, Any] | None = None
        try:
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("usage"):
                    usage = chunk["usage"]
                for choice in chunk.get("choices") or []:
                    delta = (choice.get("delta") or {}).get("content")
                    if delta:
                        parts.append(delta)
                        if on_token is not None:
                            on_token(delta)
        finally:
            await response.aclose()
        return "".join(parts), usage

    async def chat(
        self,
        messages: Sequence[Message],
        *,
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "output",
        temperature: float = 0.1,
        max_tokens: int = 1_500,
        on_token: TokenCallback | None = None,
        model: str | None = None,
    ) -> tuple[str, Usage]:
        model = model or self.model
        if not model:
            msg = f"{self.name} has no chat model configured"
            raise ProviderError(msg)
        stream = (
            on_token is not None or self.config.stream_always
        ) and self.config.supports_streaming
        started = time.perf_counter()
        while True:
            payload = self._payload(
                messages,
                json_schema=json_schema,
                schema_name=schema_name,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
                mode=self.mode,
                model=model,
            )
            try:
                text, raw_usage = await self._chat_once(
                    payload, model=model, stream=stream, on_token=on_token
                )
                break
            except ProviderError as exc:
                schema_rejected = exc.status in (400, 422) and json_schema is not None
                if schema_rejected and self.mode in _STEP_DOWN:
                    self.mode = _STEP_DOWN[self.mode]  # remember what this endpoint accepts
                    continue
                raise
        usage = Usage(latency_ms=round((time.perf_counter() - started) * 1000, 1))
        if raw_usage:
            usage.input_tokens = int(raw_usage.get("prompt_tokens") or 0)
            usage.output_tokens = int(raw_usage.get("completion_tokens") or 0)
        else:
            usage.input_tokens = sum(estimate_tokens(m.content) for m in messages)
            usage.output_tokens = estimate_tokens(text)
            usage.estimated = True
        usage.cost_usd = self._cost(usage)
        return text, usage

    async def _chat_once(
        self,
        payload: dict[str, Any],
        *,
        model: str,
        stream: bool,
        on_token: TokenCallback | None,
    ) -> tuple[str, dict[str, Any] | None]:
        url = self._url("chat/completions", model)
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.config.max_retries + 1),
            wait=wait_exponential_jitter(multiplier=0.5, max=8),
            retry=retry_if_exception(_retryable),
            reraise=True,
        ):
            with attempt:
                response = await self._post(url, payload, stream=stream)
                if stream:
                    try:
                        # Overall deadline, so a model that trickles tokens cannot run forever.
                        async with asyncio.timeout(self.config.timeout_s):
                            return await self._read_stream(response, on_token)
                    except (TimeoutError, httpx.TimeoutException) as exc:
                        raise ProviderError(
                            f"{self.name}: stream stalled: {type(exc).__name__}", timed_out=True
                        ) from exc
                    except httpx.TransportError as exc:
                        raise ProviderError(
                            f"{self.name}: stream broke: {type(exc).__name__}", retryable=True
                        ) from exc
                body = response.json()
                choices = body.get("choices") or []
                message = choices[0].get("message", {}) if choices else {}
                return str(message.get("content") or ""), body.get("usage")
        msg = "unreachable"  # pragma: no cover
        raise ProviderError(msg)  # pragma: no cover

    # --- embeddings, reranking, discovery ------------------------------------------------------

    async def embed(
        self, texts: Sequence[str], *, input_type: Literal["query", "passage"] = "passage"
    ) -> list[list[float]]:
        model = self.config.embedding_model
        if not model:
            msg = f"{self.name} has no embedding_model"
            raise ProviderError(msg)
        payload: dict[str, Any] = {"model": model, "input": list(texts), "encoding_format": "float"}
        if self.kind is ProviderKind.NVIDIA_NIM:
            payload.update({"input_type": input_type, "truncate": "END"})
        response = await self._post(self._url("embeddings", model), payload, stream=False)
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        return [list(map(float, item["embedding"])) for item in data]

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        if not (self.config.rerank_model and self.config.rerank_url):
            msg = f"{self.name} has no reranker configured"
            raise ProviderError(msg)
        payload = {
            "model": self.config.rerank_model,
            "query": {"text": query},
            "passages": [{"text": p} for p in passages],
            "truncate": "END",
        }
        response = await self._post(self.config.rerank_url, payload, stream=False)
        scores = [0.0] * len(passages)
        for item in response.json().get("rankings", []):
            scores[int(item["index"])] = float(item.get("logit", item.get("score", 0.0)))
        return scores

    async def list_models(self) -> list[str]:
        url = self._url("models", self.model)
        response = await self._client.get(url, headers=await self._headers())
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name}: HTTP {response.status_code}", status=response.status_code
            )
        # Gemini lists "models/gemini-..." but takes the bare ID in requests.
        return sorted(
            str(item.get("id")).removeprefix("models/") for item in response.json().get("data", [])
        )

    async def aclose(self) -> None:
        await self._client.aclose()
