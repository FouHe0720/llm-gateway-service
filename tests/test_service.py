import asyncio

import pytest

from app.core.config import Settings
from app.domain.errors import ProviderTimeout
from app.domain.schemas import ChatRequest
from app.providers.mock import MockProvider
from app.providers.router import ProviderRouter
from app.services.chat_service import ChatService
from tests.test_stream import events


async def test_deadline_includes_semaphore_queue(payload):
    settings = Settings(
        _env_file=None,
        gateway_auth_enabled=False,
        upstream_concurrency=1,
        gateway_request_timeout_seconds=0.02,
    )
    service = ChatService(
        ProviderRouter(settings, {"mock": MockProvider(["mock-echo"])}), settings
    )
    await service.semaphore.acquire()
    try:
        with pytest.raises(ProviderTimeout):
            await service.generate(ChatRequest(**payload), "queue-test")
    finally:
        service.semaphore.release()


async def test_stream_timeout_emits_error_and_frees_slot(payload):
    settings = Settings(
        _env_file=None,
        gateway_auth_enabled=False,
        gateway_request_timeout_seconds=0.02,
        upstream_concurrency=1,
    )
    service = ChatService(
        ProviderRouter(settings, {"mock": MockProvider(["m"], delay=1)}), settings
    )
    state = {}
    output = "".join(
        [s async for s in service.stream_events(ChatRequest(**payload), "timeout", state)]
    )
    result = events(output)
    assert [e for e, _ in result] == ["start", "error"]
    assert result[-1][1]["error"]["code"] == "provider_timeout"
    assert state["stream_error"] == "provider_timeout"
    await asyncio.wait_for(service.semaphore.acquire(), 0.5)
    service.semaphore.release()


async def test_concurrency_limit_applies_to_generate(payload):
    entered, release = asyncio.Event(), asyncio.Event()
    active, peak = 0, 0

    class SlowProvider(MockProvider):
        async def generate(self, request, model):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            entered.set()
            try:
                await release.wait()
                return await super().generate(request, model)
            finally:
                active -= 1

    settings = Settings(_env_file=None, gateway_auth_enabled=False, upstream_concurrency=1)
    service = ChatService(ProviderRouter(settings, {"mock": SlowProvider(["m"])}), settings)
    async with asyncio.TaskGroup() as tasks:
        first = tasks.create_task(service.generate(ChatRequest(**payload), "one"))
        await entered.wait()
        second = tasks.create_task(service.generate(ChatRequest(**payload), "two"))
        release.set()
    assert first.result().answer == second.result().answer
    assert peak == 1 and active == 0
