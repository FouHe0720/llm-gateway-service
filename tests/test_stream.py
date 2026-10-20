import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.domain.schemas import ChatRequest
from app.providers.base import StreamChunk
from app.providers.router import ProviderRouter
from app.services.chat_service import ChatService
from tests.test_provider import adapter


def events(text):
    return [
        (block.splitlines()[0][7:], json.loads(block.splitlines()[1][6:]))
        for block in text.strip().split("\n\n")
    ]


async def test_mock_stream(client, payload):
    response = await client.post("/v1/chat/stream", json=payload)
    result = events(response.text)
    assert response.headers["content-type"].startswith("text/event-stream")
    assert result[0][0] == "start"
    assert result[0][1]["simulated"] is True
    assert result[-1][0] == "done"
    assert result[-1][1]["usage"] is None
    assert "".join(d["delta"] for e, d in result if e == "delta") == "[mock] Hello Gateway"
    assert {d["request_id"] for _, d in result} == {response.headers["x-request-id"]}


async def test_stream_unknown_model_returns_http_error(client, payload):
    payload["model"] = "missing"
    assert (await client.post("/v1/chat/stream", json=payload)).status_code == 404


class FixtureStream(httpx.AsyncByteStream):
    def __init__(self, frames):
        self.frames = frames
        self.closed = False

    async def __aiter__(self):
        for frame in self.frames:
            yield frame

    async def aclose(self):
        self.closed = True


async def test_http_incremental_stream_usage_and_cleanup(payload):
    upstream = FixtureStream(
        [
            b': heartbeat\n\ndata: {"choices":[{"delta":{"content":"one"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"two"}}]}\r\n\r\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":1,"completion_tokens":2,',
            b'"total_tokens":3}}\n\ndata: [DONE]\n\n',
        ]
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=upstream
            )
        )
    ) as client:
        result = [c async for c in adapter(client).stream(ChatRequest(**payload), "raw")]
        assert [c.delta for c in result] == ["one", "two", ""]
        assert result[-1].usage.total_tokens == 3
    assert upstream.closed


@pytest.mark.parametrize(
    "frames",
    [
        [b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'],
        [b"data: invalid\n\n"],
        [b"data: " + b"x" * 65537],
    ],
)
async def test_broken_stream_is_not_retried(payload, frames):
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=FixtureStream(frames)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(Exception, match="provider_error"):
            async for _ in adapter(client).stream(ChatRequest(**payload), "raw"):
                pass
    assert calls == 1


async def test_generator_close_releases_concurrency_slot(payload):
    closed = asyncio.Event()

    class CancellableProvider:
        async def stream(self, *_):
            try:
                yield StreamChunk("first")
                await asyncio.sleep(10)
            finally:
                closed.set()

    settings = Settings(_env_file=None, gateway_auth_enabled=False, upstream_concurrency=1)
    service = ChatService(ProviderRouter(settings, {"mock": CancellableProvider()}), settings)
    iterator = service.stream_events(ChatRequest(**payload), "test", {})
    assert "event: start" in await anext(iterator)
    assert "event: delta" in await anext(iterator)
    await iterator.aclose()
    assert closed.is_set()
    await asyncio.wait_for(service.semaphore.acquire(), 0.5)
    service.semaphore.release()
