import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.core.trace import record_attempt, trace_headers
from app.domain.errors import ProviderError, ProviderTimeout
from app.domain.schemas import ChatRequest, ProviderTiming, Usage
from app.providers.base import Generation, StreamChunk
from app.providers.openai_compatible import OpenAICompatibleProvider, status_error


class OllamaProvider(OpenAICompatibleProvider):
    """Native /api/chat preserves Ollama nanosecond timings; NDJSON becomes gateway SSE."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.url = self.url.removesuffix("/chat/completions") + "/api/chat"

    def payload(self, request: ChatRequest, model: str, stream: bool) -> dict[str, Any]:
        options = {
            "num_ctx": self.settings.ollama_context_length,
            "num_predict": request.max_tokens or self.settings.ollama_default_max_tokens,
        }
        for field in ("temperature", "top_p", "seed"):
            value = getattr(request, field)
            if value is not None:
                options[field] = value
        return {
            "model": model,
            "messages": [m.model_dump() for m in request.messages],
            "stream": stream,
            "options": options,
            "keep_alive": self.settings.ollama_keep_alive,
        }

    def decode_generation(self, data: Any) -> Generation:
        if not data.get("done") or "error" in data:
            raise ProviderError("Ollama did not complete generation")
        answer = data["message"]["content"]
        if not isinstance(answer, str):
            raise ProviderError("Ollama did not return text")
        usage = None
        if "eval_count" in data and "prompt_eval_count" in data:
            usage = Usage(
                prompt_tokens=data["prompt_eval_count"],
                completion_tokens=data["eval_count"],
                total_tokens=data["prompt_eval_count"] + data["eval_count"],
            )
        timing = ProviderTiming(
            load_duration_ns=data.get("load_duration"),
            eval_duration_ns=data.get("eval_duration"),
            prompt_eval_duration_ns=data.get("prompt_eval_duration"),
            eval_count=data.get("eval_count"),
        )
        return Generation(answer=answer, usage=usage, timing=timing)

    async def stream(
        self, request: ChatRequest, model: str
    ) -> AsyncGenerator[StreamChunk, None]:
        try:
            record_attempt()
            async with self.client.stream(
                "POST",
                self.url,
                headers=trace_headers(),
                json=self.payload(request, model, True),
            ) as response:
                if response.status_code >= 300:
                    raise status_error(response.status_code)
                pending = bytearray()
                async for piece in response.aiter_bytes():
                    pending.extend(piece)
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        pending = bytearray(rest)
                        if len(line) > 65_536:
                            raise ProviderError("Ollama frame too large")
                        if not line.strip():
                            continue
                        data = json.loads(line)
                        if "error" in data:
                            raise ProviderError()
                        delta = data.get("message", {}).get("content", "")
                        if not isinstance(delta, str):
                            raise ProviderError("Ollama stream text invalid")
                        if data.get("done"):
                            result = self.decode_generation(data)
                            yield StreamChunk(delta, result.usage, result.timing)
                            return
                        if delta:
                            yield StreamChunk(delta)
                    if len(pending) > 65_536:
                        raise ProviderError("Ollama frame too large")
                raise ProviderError("Ollama stream ended before done")
        except httpx.TimeoutException:
            raise ProviderTimeout() from None
        except httpx.HTTPError:
            raise ProviderError("Ollama transport failed") from None
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderError("Invalid Ollama response") from None
