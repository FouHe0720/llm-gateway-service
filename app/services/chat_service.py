import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from time import perf_counter

import anyio

from app.core.config import Settings
from app.domain.errors import GatewayError, ProviderTimeout
from app.domain.schemas import ChatRequest, ChatResponse
from app.providers.router import ProviderRouter


class ChatService:
    def __init__(self, router: ProviderRouter, settings: Settings) -> None:
        self.router = router
        self.settings = settings
        self.semaphore = asyncio.Semaphore(settings.upstream_concurrency)

    async def generate(self, request: ChatRequest, request_id: str) -> ChatResponse:
        provider, mapping = self.router.resolve(request.model)
        started = perf_counter()
        try:
            async with asyncio.timeout(self.settings.gateway_request_timeout_seconds):
                async with self.semaphore:
                    result = await provider.generate(request, mapping.upstream_model)
        except TimeoutError:
            raise ProviderTimeout() from None
        return ChatResponse(
            answer=result.answer,
            model=request.model,
            request_id=request_id,
            usage=result.usage,
            latency_ms=round((perf_counter() - started) * 1000, 3),
        )

    async def stream_events(
        self, request: ChatRequest, request_id: str, state: dict
    ) -> AsyncIterator[str]:
        provider, mapping = self.router.resolve(request.model)
        started = perf_counter()
        usage = None
        common = {"model": request.model, "request_id": request_id}
        yield encode_event("start", {**common, "simulated": mapping.provider == "mock"})
        iterator = provider.stream(request, mapping.upstream_model)
        try:
            async with asyncio.timeout(self.settings.gateway_request_timeout_seconds):
                async with self.semaphore:
                    async with aclosing(iterator):
                        async for chunk in iterator:
                            if chunk.usage:
                                usage = chunk.usage
                            if chunk.delta:
                                yield encode_event("delta", {**common, "delta": chunk.delta})
            yield encode_event(
                "done",
                {
                    **common,
                    "usage": usage.model_dump() if usage else None,
                    "latency_ms": round((perf_counter() - started) * 1000, 3),
                },
            )
        except TimeoutError:
            state["stream_error"] = "provider_timeout"
            yield error_event(ProviderTimeout(), request_id)
        except GatewayError as exc:
            state["stream_error"] = exc.code
            yield error_event(exc, request_id)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        except Exception:
            state["stream_error"] = "internal_error"
            yield error_event(
                GatewayError("internal_error", "Unexpected gateway error"), request_id
            )
        finally:
            # Cleanup must finish even inside StreamingResponse's disconnect cancel scope.
            with anyio.CancelScope(shield=True):
                await iterator.aclose()


def encode_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def error_event(exc: GatewayError, request_id: str) -> str:
    return encode_event(
        "error", {"error": {"code": exc.code, "message": exc.message, "request_id": request_id}}
    )
