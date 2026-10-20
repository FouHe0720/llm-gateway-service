import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import ModelMapping, Settings
from app.main import create_app
from tests.helpers import app_client, live_server
from tests.test_auth import TEST_KEY
from tests.test_stream import events


def local_config(url, **kwargs):
    return dict(
        gateway_api_key=TEST_KEY,
        gateway_models=[ModelMapping(model="fixture", provider="local", upstream_model="raw")],
        local_base_url=url + "/v1",
        upstream_retry_base_seconds=0,
        **kwargs,
    )


@pytest.mark.parametrize(
    "status,expected,code,attempts",
    [
        (503, 502, "provider_error", 3),
        (429, 429, "provider_rate_limited", 3),
        (401, 502, "provider_error", 1),
        (200, 200, None, 1),
    ],
)
async def test_real_http_fault_injection(status, expected, code, attempts):
    upstream = FastAPI()
    calls = 0

    @upstream.post("/v1/chat/completions")
    async def completion():
        nonlocal calls
        calls += 1
        if status != 200:
            return JSONResponse({"private": "never-return-this"}, status_code=status)
        return {"choices": [{"message": {"content": "fixture answer"}}]}

    async with live_server(upstream) as url:
        async with app_client(**local_config(url)) as (_, client):
            response = await client.post(
                "/v1/chat",
                json={
                    "model": "fixture",
                    "messages": [{"role": "user", "content": "public example"}],
                },
                headers={"Authorization": f"Bearer {TEST_KEY}", "X-Request-ID": "fault-test"},
            )
            assert response.status_code == expected
            assert response.headers["x-request-id"] == "fault-test"
            assert "never-return-this" not in response.text
            if code:
                assert response.json()["error"]["code"] == code
            assert calls == attempts


async def test_real_http_read_timeout_is_not_retried():
    upstream = FastAPI()
    calls = 0

    @upstream.post("/v1/chat/completions")
    async def completion():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.15)
        return {}

    async with live_server(upstream) as url:
        async with app_client(**local_config(url, upstream_read_timeout_seconds=0.03)) as (
            _,
            client,
        ):
            response = await client.post(
                "/v1/chat",
                json={"model": "fixture", "messages": [{"role": "user", "content": "test"}]},
                headers={"Authorization": f"Bearer {TEST_KEY}"},
            )
            assert response.status_code == 504
            assert calls == 1


async def test_real_tcp_stream_is_incremental_and_disconnect_cleans_up():
    upstream = FastAPI()
    release = asyncio.Event()
    closed = asyncio.Event()
    calls = 0

    @upstream.post("/v1/chat/completions")
    async def completion(request: Request):
        nonlocal calls
        calls += 1
        body = await request.json()
        assert body["stream"] is True
        assert body["model"] == "raw"

        async def chunks():
            try:
                yield 'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
                await release.wait()  # First chunk MUST reach the client before this opens.
                yield 'data: {"choices":[{"delta":{"content":"second"}}]}\n\n'
                await asyncio.sleep(10)
            finally:
                closed.set()

        return StreamingResponse(chunks(), media_type="text/event-stream")

    async with live_server(upstream) as url:
        gateway = create_app(
            Settings(_env_file=None, **local_config(url, upstream_concurrency=1))
        )
        async with live_server(gateway) as gateway_url:
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                async with client.stream(
                    "POST",
                    gateway_url + "/v1/chat/stream",
                    json={
                        "model": "fixture",
                        "messages": [{"role": "user", "content": "test"}],
                    },
                    headers={"Authorization": f"Bearer {TEST_KEY}"},
                ) as response:
                    async with asyncio.timeout(2):
                        async for line in response.aiter_lines():
                            if (
                                line.startswith("data:")
                                and json.loads(line[5:]).get("delta") == "first"
                            ):
                                break
                    assert not release.is_set()
                await asyncio.wait_for(closed.wait(), 2)
                await asyncio.wait_for(gateway.state.chat.semaphore.acquire(), 2)
                gateway.state.chat.semaphore.release()
                async with asyncio.timeout(2):
                    while gateway.state.metrics.active:  # noqa: ASYNC110
                        await asyncio.sleep(0.01)
                assert (
                    gateway.state.metrics.snapshot()["cancelled_total"]["/v1/chat/stream"] == 1
                )
                assert calls == 1


async def test_stream_upstream_error_event_and_metric():
    upstream = FastAPI()

    @upstream.post("/v1/chat/completions")
    async def completion():
        return JSONResponse({}, status_code=429)

    async with live_server(upstream) as url:
        async with app_client(**local_config(url)) as (app, client):
            response = await client.post(
                "/v1/chat/stream",
                json={"model": "fixture", "messages": [{"role": "user", "content": "test"}]},
                headers={"Authorization": f"Bearer {TEST_KEY}"},
            )
            result = events(response.text)
            assert [kind for kind, _ in result] == ["start", "error"]
            assert result[-1][1]["error"]["code"] == "provider_rate_limited"
            assert app.state.metrics.snapshot()["failures_total"]["/v1/chat/stream"] == 1
