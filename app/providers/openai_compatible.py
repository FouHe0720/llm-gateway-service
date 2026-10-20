import asyncio
import json
import random
from collections.abc import AsyncIterator
from typing import Any

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.domain.errors import ProviderError, ProviderRateLimit, ProviderTimeout
from app.domain.schemas import ChatRequest, Usage
from app.providers.base import Generation, StreamChunk

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRYABLE_NETWORK = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError)


def status_error(status: int) -> ProviderError:
    if status == 429:
        return ProviderRateLimit()
    return ProviderError()  # Never expose upstream body, URL, headers, or credentials.


def parse_usage(value: Any) -> Usage | None:
    return Usage.model_validate(value) if value is not None else None


class OpenAICompatibleProvider:
    """Shared async client; one bounded retry policy for non-streaming generation."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        base_url: str,
        api_key: str | None,
        models: list[str],
    ) -> None:
        self.client = client
        self.settings = settings
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.models = models

    def list_models(self) -> list[str]:
        return self.models.copy()

    def payload(self, request: ChatRequest, model: str, stream: bool) -> dict[str, Any]:
        body = request.model_dump(exclude_none=True)
        body.update(model=model, stream=stream)
        if stream:
            body["stream_options"] = {"include_usage": True}
        return body

    async def _backoff(self, attempt: int) -> None:
        ceiling = self.settings.upstream_retry_base_seconds * 2**attempt
        await asyncio.sleep(
            random.uniform(0, ceiling)
        )  # Full jitter, bounded by total deadline.

    async def _read_json(self, response: httpx.Response) -> Any:
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > self.settings.upstream_max_response_bytes:
                raise ProviderError("Upstream response exceeded configured size limit")
        return json.loads(data)

    async def generate(self, request: ChatRequest, model: str) -> Generation:
        attempts = self.settings.upstream_max_retries + 1
        for attempt in range(attempts):
            try:
                async with self.client.stream(
                    "POST",
                    self.url,
                    headers=self.headers,
                    json=self.payload(request, model, False),
                ) as response:
                    if response.status_code >= 300:
                        if (
                            response.status_code not in RETRYABLE_STATUS
                            or attempt == attempts - 1
                        ):
                            raise status_error(response.status_code)
                    else:
                        data = await self._read_json(response)
                        answer = data["choices"][0]["message"]["content"]
                        if not isinstance(answer, str):
                            raise ProviderError("Upstream did not return text content")
                        return Generation(answer=answer, usage=parse_usage(data.get("usage")))
            except RETRYABLE_NETWORK as exc:
                if attempt == attempts - 1:
                    if isinstance(exc, httpx.TimeoutException):
                        raise ProviderTimeout() from None
                    raise ProviderError("Upstream connection failed") from None
            except httpx.TimeoutException:
                # A read timeout may follow successful generation: no automatic replay.
                raise ProviderTimeout() from None
            except httpx.HTTPError:
                raise ProviderError("Upstream transport failed") from None
            except (ValueError, KeyError, IndexError, TypeError, ValidationError):
                raise ProviderError(
                    "Upstream response was not valid text completion JSON"
                ) from None
            await self._backoff(attempt)
        raise ProviderError()  # Defensive: every final attempt returns or raises.

    async def _events(self, response: httpx.Response) -> AsyncIterator[str]:
        # Incremental byte framing bounds a malicious event before aiter_lines can buffer it.
        pending = bytearray()
        event: list[str] = []
        size = 0
        async for chunk in response.aiter_bytes():
            pending.extend(chunk)
            while b"\n" in pending:
                line, _, rest = pending.partition(b"\n")
                pending = bytearray(rest)
                size += len(line)
                if size > 65_536:
                    raise ProviderError("Upstream SSE event too large")
                text = line.rstrip(b"\r").decode("utf-8")
                if not text:
                    if event:
                        yield "\n".join(event)
                    event, size = [], 0
                elif text.startswith("data:"):
                    event.append(text[5:].lstrip(" "))
            if len(pending) + size > 65_536:
                raise ProviderError("Upstream SSE event too large")
        if pending or event:
            raise ProviderError("Upstream SSE event was truncated")

    async def stream(self, request: ChatRequest, model: str) -> AsyncIterator[StreamChunk]:
        # The gateway has sent `start`: never retry or replay any streaming request.
        try:
            async with self.client.stream(
                "POST", self.url, headers=self.headers, json=self.payload(request, model, True)
            ) as response:
                if response.status_code >= 300:
                    raise status_error(response.status_code)
                if "text/event-stream" not in response.headers.get("content-type", ""):
                    raise ProviderError("Upstream did not return SSE")
                async for event in self._events(response):
                    if event.strip() == "[DONE]":
                        return
                    data = json.loads(event)
                    if "error" in data:
                        raise ProviderError()
                    usage = parse_usage(data.get("usage"))
                    choices = data.get("choices", [])
                    delta = choices[0].get("delta", {}).get("content") if choices else None
                    if delta is not None and not isinstance(delta, str):
                        raise ProviderError("Upstream stream did not contain text")
                    if delta or usage:
                        yield StreamChunk(delta=delta or "", usage=usage)
                raise ProviderError("Upstream stream ended without [DONE]")
        except httpx.TimeoutException:
            raise ProviderTimeout() from None
        except httpx.HTTPError:
            raise ProviderError("Upstream stream transport failed") from None
        except (ValueError, KeyError, IndexError, TypeError, ValidationError):
            raise ProviderError("Upstream SSE payload was invalid") from None
