"""One HTTP client for every OpenAI-compatible endpoint: NIM, Azure OpenAI, Gemini, OpenAI, vLLM.

Differences between providers are confined to URL construction, authentication, and how JSON
output is requested. Each ``chat`` sends exactly one request, so the router can count every
request against the provider's limits (aria.llm.quota) before it goes:

* A failed request is not retried here. The router hands the call to the next provider, ARIA's
  one retry layer, and a refusal for a limit (HTTP 429) is classified (aria.llm.ratelimit) so the
  router rests the provider for as long as the limit lasts.
* If a provider rejects the configured structured-output mode, the client steps down
  (json_schema -> guided_json -> json_object -> prompt), remembers what it will try next, and
  raises with ``resend`` set: the router admits the same request again in the new mode.
* A model that declines (a refusal, or ``finish_reason == "content_filter"`` and Gemini's like)
  raises ``ModelRefusalError``. JSON cut short by ``max_tokens`` (``finish_reason == "length"``)
  raises ``OutputTruncatedError`` and is never parsed; text cut short is returned with
  ``Usage.finish_reason == "length"``.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
from pydantic import SecretStr

from aria.config import ProviderConfig, ProviderKind, StructuredOutputMode
from aria.llm.base import (
    Message,
    ProviderError,
    TokenCallback,
    Usage,
    check_stop,
    estimate_tokens,
    finish_reason,
)
from aria.llm.ratelimit import classify, retry_after_seconds

_AZURE_SCOPE = "https://cognitiveservices.azure.com/.default"
_STEP_DOWN = {
    StructuredOutputMode.JSON_SCHEMA: StructuredOutputMode.GUIDED_JSON,
    StructuredOutputMode.GUIDED_JSON: StructuredOutputMode.JSON_OBJECT,
    StructuredOutputMode.JSON_OBJECT: StructuredOutputMode.PROMPT,
}
# A 400 or 422 that names how JSON was asked for: step down. Any other is a plain failure, so a
# request the provider refuses for another reason is not sent three more times.
_SCHEMA_WORDS = re.compile(
    r"response_format|json_schema|schema|guided_json|nvext|json[ _]mode|json_object|"
    r"structured output|response_mime_type",
    re.IGNORECASE,
)


@dataclass
class _Answer:
    """One reply as it arrived: its text, usage block, finish reason, any refusal, and the
    response's id and model."""

    text: str = ""
    usage: dict[str, Any] | None = None
    finish: str | None = None
    refusal: str = ""
    response_id: str | None = None
    model: str | None = None
    parts: list[str] = field(default_factory=list)


def _string(value: Any) -> str | None:
    """A short identifier from a reply (its id or model), or None when it gave none."""
    return value[:200] if isinstance(value, str) and value else None


def _merge_system(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """The conversation with its system messages folded into the first user message, for a
    model that refuses the system role."""
    system = [m["content"] for m in messages if m["role"] == "system"]
    turns = [dict(m) for m in messages if m["role"] != "system"]
    if not system:
        return turns
    preface = "\n\n".join(system)
    for turn in turns:
        if turn["role"] == "user":
            turn["content"] = f"{preface}\n\n{turn['content']}"
            return turns
    return [{"role": "user", "content": preface}, *turns]


class OpenAICompatibleProvider:
    def __init__(
        self,
        name: str,
        config: ProviderConfig,
        client: httpx.AsyncClient | None = None,
        *,
        api_key: SecretStr | None = None,
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
        # A key given here (a visitor's own) replaces the one the config names; never both.
        self._api_key = api_key

    def _key(self) -> SecretStr | None:
        return self._api_key if self._api_key is not None else self.config.api_key()

    def _scrub(self, text: str) -> str:
        """``text`` without the key, should a provider ever echo it back in an error."""
        key = self._key()
        secret = key.get_secret_value() if key is not None else ""
        return text.replace(secret, "[key]") if secret else text

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
        headers = {
            **self.config.extra_headers,
            "Content-Type": "application/json",
            "Accept": accept,
        }
        if self.kind is ProviderKind.AZURE_OPENAI and self.config.azure_ad:
            if self._credential is None:
                from azure.identity.aio import DefaultAzureCredential  # noqa: PLC0415 - optional extra

                self._credential = DefaultAzureCredential()
            token = await self._credential.get_token(_AZURE_SCOPE)
            headers["Authorization"] = f"Bearer {token.token}"
            return headers
        key = self._key()
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
            # so the router fails over at once.
            raise ProviderError(
                self._scrub(f"{self.name}: {type(exc).__name__}: {exc}"), timed_out=True
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderError(
                self._scrub(f"{self.name}: {type(exc).__name__}: {exc}"), retryable=True
            ) from exc
        if response.status_code >= 400:
            raise await self._refusal(response)
        return response

    async def _refusal(self, response: httpx.Response) -> ProviderError:
        """A failed response as the router's error: what the provider said, whether another
        provider might do better, and which limit it names, if any."""
        status = response.status_code
        try:
            raw = self._scrub((await response.aread()).decode(errors="replace"))
        except httpx.HTTPError as exc:  # the body broke off: the status still says enough
            raw = f"(body unreadable: {type(exc).__name__})"
        finally:
            await response.aclose()
        now = time.time()
        return ProviderError(
            f"{self.name}: HTTP {status}: {raw[:500]}",
            status=status,
            retryable=status in (408, 409, 429) or status >= 500,
            retry_after=retry_after_seconds(response.headers, raw, now=now),
            limit=classify(status, raw, response.headers, now=now),
        )

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
            self.config.max_tokens_field: max_tokens + self.config.reasoning_tokens,
            "stream": stream,
        }
        if self.config.sampling:
            payload["temperature"] = temperature
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
        if self.config.system_messages == "merge":
            payload["messages"] = _merge_system(msgs)
        payload.update(self.config.extra_body)
        return payload

    async def _read_stream(
        self, response: httpx.Response, on_token: TokenCallback | None
    ) -> _Answer:
        """The streamed reply: its text, usage, finish reason, any refusal it carried, and the
        response's id and model (every chunk repeats them)."""
        answer = _Answer()
        refusal: list[str] = []
        try:
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError as exc:
                    msg = f"{self.name}: the stream sent a chunk that is not JSON"
                    raise ProviderError(msg, retryable=True) from exc
                if not isinstance(chunk, dict):
                    continue
                if chunk.get("usage"):
                    answer.usage = chunk["usage"]
                answer.response_id = _string(chunk.get("id")) or answer.response_id
                answer.model = _string(chunk.get("model")) or answer.model
                for choice in chunk.get("choices") or []:
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta")
                    delta = delta if isinstance(delta, dict) else {}
                    answer.finish = choice.get("finish_reason") or answer.finish
                    if delta.get("refusal"):
                        refusal.append(str(delta["refusal"]))
                    content = delta.get("content")
                    if content:
                        answer.parts.append(content)
                        if on_token is not None:
                            on_token(content)
        finally:
            await response.aclose()
        answer.text, answer.refusal = "".join(answer.parts), "".join(refusal)
        return answer

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
            answer = await self._chat_once(payload, model=model, stream=stream, on_token=on_token)
        except ProviderError as exc:
            schema_rejected = (
                exc.status in (400, 422)
                and json_schema is not None
                and bool(_SCHEMA_WORDS.search(str(exc)))
            )
            if schema_rejected and self.mode in _STEP_DOWN:
                self.mode = _STEP_DOWN[self.mode]  # remember what this endpoint accepts
                exc.resend = True
            raise
        usage = Usage(
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
            finish_reason=finish_reason(answer.finish),
            response_id=answer.response_id,
            response_model=answer.model,
        )
        if answer.usage:
            usage.input_tokens = int(answer.usage.get("prompt_tokens") or 0)
            usage.output_tokens = int(answer.usage.get("completion_tokens") or 0)
        else:
            usage.input_tokens = sum(estimate_tokens(m.content) for m in messages)
            usage.output_tokens = estimate_tokens(answer.text)
            usage.estimated = True
        usage.cost_usd = self._cost(usage)
        # A refusal or content filter, or JSON cut short, raises a typed error that carries
        # what the call cost; neither reply is ever returned as an answer.
        check_stop(self.name, usage, structured=json_schema is not None, refusal=answer.refusal)
        return answer.text, usage

    async def _chat_once(
        self,
        payload: dict[str, Any],
        *,
        model: str,
        stream: bool,
        on_token: TokenCallback | None,
    ) -> _Answer:
        """Send the request once: text, usage, finish reason, any refusal, id and model."""
        response = await self._post(self._url("chat/completions", model), payload, stream=stream)
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
        try:
            body = response.json()
        except ValueError as exc:
            msg = f"{self.name}: the reply is not JSON"
            raise ProviderError(msg, retryable=True) from exc
        body = body if isinstance(body, dict) else {}
        choices = body.get("choices") or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = choice.get("message") or {}
        usage = body.get("usage")
        return _Answer(
            text=str(message.get("content") or ""),
            usage=usage if isinstance(usage, dict) else None,
            finish=choice.get("finish_reason"),
            refusal=str(message.get("refusal") or ""),
            response_id=_string(body.get("id")),
            model=_string(body.get("model")),
        )

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
        try:
            response = await self._client.get(url, headers=await self._headers())
        except httpx.HTTPError as exc:
            raise ProviderError(
                self._scrub(f"{self.name}: {type(exc).__name__}: {exc}"), retryable=True
            ) from exc
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
