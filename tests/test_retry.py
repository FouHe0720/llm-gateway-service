import httpx
import pytest

from app.domain.errors import ProviderError, ProviderRateLimit, ProviderTimeout
from app.domain.schemas import ChatRequest
from tests.test_provider import adapter


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_retry_success_and_bound(payload, status):
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(status)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await adapter(client, upstream_retry_base_seconds=0).generate(
            ChatRequest(**payload), "raw"
        )
        assert result.answer == "ok"
        assert calls == 3


@pytest.mark.parametrize(
    "status,error,attempts", [(429, ProviderRateLimit, 3), (401, ProviderError, 1)]
)
async def test_retry_exhaustion_or_non_retryable(payload, status, error, attempts):
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="upstream-secret-must-not-escape")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(error) as exc:
            await adapter(client, upstream_retry_base_seconds=0).generate(
                ChatRequest(**payload), "m"
            )
        assert "secret" not in exc.value.message
        assert calls == attempts


@pytest.mark.parametrize(
    "exception,expected,attempts",
    [
        (httpx.ConnectError, ProviderError, 3),
        (httpx.ConnectTimeout, ProviderTimeout, 3),
        (httpx.ReadTimeout, ProviderTimeout, 1),
    ],
)
async def test_network_error_policy(payload, exception, expected, attempts):
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        raise exception("sensitive internal endpoint")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(expected):
            await adapter(client, upstream_retry_base_seconds=0).generate(
                ChatRequest(**payload), "m"
            )
        assert calls == attempts
