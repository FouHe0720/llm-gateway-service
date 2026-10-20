import json

import httpx
import pytest

from app.core.config import ModelMapping, Settings
from app.domain.errors import ProviderError
from app.domain.schemas import ChatRequest
from app.providers.local import LocalProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.router import ProviderRouter


def adapter(client, **kwargs):
    settings = Settings(_env_file=None, gateway_auth_enabled=False, **kwargs)
    return OpenAICompatibleProvider(
        client, settings, "http://upstream.test/v1", "fixture", ["raw"]
    )


async def test_generate_maps_payload_and_preserves_usage(payload):
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "raw"
        assert body["stream"] is False
        assert request.headers["authorization"] == "Bearer fixture"
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = adapter(client)
        result = await provider.generate(ChatRequest(**payload), "raw")
        assert result.answer == "answer"
        assert result.usage.total_tokens == 3
        assert provider.list_models() == ["raw"]
        assert issubclass(LocalProvider, OpenAICompatibleProvider)


@pytest.mark.parametrize(
    "data", [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}]
)
async def test_bad_response_is_sanitized(payload, data):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))
    ) as client:
        with pytest.raises(ProviderError):
            await adapter(client).generate(ChatRequest(**payload), "raw")


async def test_response_size_bound(payload):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 2048))
    ) as client:
        with pytest.raises(ProviderError, match="provider_error"):
            await adapter(client, upstream_max_response_bytes=1024).generate(
                ChatRequest(**payload), "raw"
            )


def test_disabled_model_and_public_mapping():
    settings = Settings(
        _env_file=None,
        gateway_auth_enabled=False,
        gateway_models=[
            ModelMapping(model="visible", provider="mock"),
            ModelMapping(model="hidden", provider="mock", enabled=False),
        ],
    )
    router = ProviderRouter(settings, {})
    assert [m.model for m in router.list_models()] == ["visible"]
    with pytest.raises(Exception, match="model_not_found"):
        router.resolve("hidden")
