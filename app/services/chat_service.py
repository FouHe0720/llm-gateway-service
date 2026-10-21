import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from time import perf_counter

import anyio

from app.core.config import Settings
from app.core.trace import RequestTrace, current_trace
from app.domain.errors import GatewayError, ProviderError, ProviderTimeout
from app.domain.schemas import ChatRequest, ChatResponse, ResponseMetadata
from app.infra.cache import ResponseCache, cache_key
from app.providers.router import ProviderRouter


class ChatService:
    def __init__(self, router: ProviderRouter, settings: Settings) -> None:
        self.router, self.settings = router, settings
        self.semaphore = asyncio.Semaphore(settings.upstream_concurrency)
        self.cache = ResponseCache(
            settings.gateway_cache_ttl_seconds,
            settings.gateway_cache_max_entries,
            settings.gateway_cache_max_bytes,
        )

    async def generate(self, request: ChatRequest, request_id: str) -> ChatResponse:
        alias = self.router.route(request.model, request.task_type)
        provider, mapping = self.router.resolve(alias)
        started = perf_counter()
        metadata = ResponseMetadata(served_model=alias)
        cacheable = self.settings.gateway_cache_enabled and request.temperature == 0
        metadata.cache_status = (
            "miss"
            if cacheable
            else "bypass"
            if self.settings.gateway_cache_enabled
            else "disabled"
        )
        key = (
            cache_key(
                request.model_copy(update={"model": alias}),
                mapping.model_dump_json(),
            )
            if cacheable
            else ""
        )
        result = self.cache.get(key) if cacheable else None
        if result is not None:
            metadata.cache_status = "hit"
        else:
            trace = RequestTrace(self.settings.gateway_max_provider_attempts, request_id)
            token = current_trace.set(trace)
            try:
                async with asyncio.timeout(self.settings.gateway_request_timeout_seconds):
                    queued = perf_counter()
                    async with self.semaphore:
                        metadata.queue_ms = round((perf_counter() - queued) * 1000, 3)
                        try:
                            result = await provider.generate(request, mapping.upstream_model)
                        except ProviderError as exc:
                            if not mapping.fallback_model or not getattr(
                                exc, "fallback_allowed", True
                            ):
                                raise
                            fallback, target = self.router.resolve(mapping.fallback_model)
                            metadata.fallback_count = 1
                            metadata.served_model = target.model
                            result = await fallback.generate(request, target.upstream_model)
            except TimeoutError:
                exc = ProviderTimeout()
                exc.metadata = metadata
                raise exc from None
            except GatewayError as exc:
                exc.metadata = metadata
                raise
            finally:
                metadata.attempts, metadata.retries = trace.attempts, trace.retries
                current_trace.reset(token)
            if cacheable and not metadata.fallback_count:
                self.cache.put(key, result)
        metadata.timing = result.timing
        return ChatResponse(
            answer=result.answer,
            model=request.model,
            request_id=request_id,
            usage=result.usage,
            latency_ms=round((perf_counter() - started) * 1000, 3),
            metadata=metadata,
        )

    async def stream_events(
        self, request: ChatRequest, request_id: str, state: dict
    ) -> AsyncIterator[str]:
        alias = self.router.route(request.model, request.task_type)
        provider, mapping = self.router.resolve(alias)
        started = perf_counter()
        usage = None
        metadata = ResponseMetadata(
            served_model=alias,
            cache_status="bypass" if self.settings.gateway_cache_enabled else "disabled",
        )
        common = {"model": request.model, "request_id": request_id}
        yield encode_event("start", {**common, "simulated": mapping.provider == "mock"})
        iterator = provider.stream(request, mapping.upstream_model)
        trace = RequestTrace(1, request_id)
        token = current_trace.set(trace)
        try:
            async with asyncio.timeout(self.settings.gateway_request_timeout_seconds):
                queued = perf_counter()
                async with self.semaphore:
                    metadata.queue_ms = round((perf_counter() - queued) * 1000, 3)
                    async with aclosing(iterator):
                        async for chunk in iterator:
                            if chunk.usage:
                                usage = chunk.usage
                            if chunk.timing:
                                metadata.timing = chunk.timing
                            if chunk.delta:
                                yield encode_event("delta", {**common, "delta": chunk.delta})
            metadata.attempts = trace.attempts
            yield encode_event(
                "done",
                {
                    **common,
                    "usage": usage.model_dump() if usage else None,
                    "latency_ms": round((perf_counter() - started) * 1000, 3),
                    "metadata": metadata.model_dump(),
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
            with anyio.CancelScope(shield=True):
                await iterator.aclose()
            current_trace.reset(token)


def encode_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def error_event(exc: GatewayError, request_id: str) -> str:
    return encode_event(
        "error", {"error": {"code": exc.code, "message": exc.message, "request_id": request_id}}
    )
