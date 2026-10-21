import json

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import ModelMapping, Settings
from app.domain.errors import ProviderError
from app.domain.schemas import ChatRequest
from app.infra.cache import ResponseCache, cache_key
from app.providers.base import Generation
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider
from app.providers.router import ProviderRouter
from app.services.chat_service import ChatService
from tests.helpers import app_client


def test_cache_ttl_lru_and_bytes(monkeypatch):
    now = 0
    monkeypatch.setattr("app.infra.cache.monotonic", lambda: now)
    cache = ResponseCache(5, 2, 1024)
    cache.put("a", Generation("A"))
    cache.put("b", Generation("B"))
    assert cache.get("a").answer == "A"
    cache.put("c", Generation("C"))
    assert cache.get("b") is None
    cache.put("oversize", Generation("x" * 2048))
    assert cache.get("oversize") is None
    now = 6
    assert cache.get("a") is None
    cache.put("d", Generation("D"))
    assert len(cache.entries) == 1


async def test_cache_preserves_content_but_not_usage_or_request_id(payload):
    async with app_client(gateway_auth_enabled=False, gateway_cache_enabled=True) as (_, c):
        payload["temperature"] = 0
        one = (await c.post("/v1/chat", json=payload)).json()
        two = (await c.post("/v1/chat", json=payload)).json()
        assert one["answer"] == two["answer"]
        assert one["request_id"] != two["request_id"]
        assert one["metadata"]["cache_status"] == "miss"
        assert two["metadata"]["cache_status"] == "hit"
        assert two["metadata"]["attempts"] == 0 and two["usage"] is None
        payload["temperature"] = 0.5
        assert (await c.post("/v1/chat", json=payload)).json()["metadata"][
            "cache_status"
        ] == "bypass"


def test_cache_key_contains_all_parameters(payload):
    a = ChatRequest(**payload)
    b = a.model_copy(update={"seed": 42})
    assert cache_key(a, "a") != cache_key(b, "a")
    assert cache_key(a, "a") != cache_key(a, "b")


async def test_single_hop_fallback_and_task_route(payload):
    class Broken(MockProvider):
        async def generate(self, *args):
            raise ProviderError()

    settings = Settings(
        _env_file=None,
        gateway_auth_enabled=False,
        gateway_models=[
            ModelMapping(model="primary", provider="mock", fallback_model="backup"),
            ModelMapping(model="backup", provider="mock"),
        ],
        gateway_task_routes={"reasoning": "primary"},
    )
    router = ProviderRouter(settings, {"mock": Broken(["m"])})

    class BackupRouter(ProviderRouter):
        def resolve(self, model):
            _, mapping = super().resolve(model)
            return (MockProvider(["m"]) if model == "backup" else Broken(["m"])), mapping

    service = ChatService(BackupRouter(settings, {}), settings)
    # Supply both provider registrations; router resolution stays real.
    service.router.providers = {"mock": MockProvider(["m"])}
    result = await service.generate(
        ChatRequest(**{**payload, "model": "auto", "task_type": "reasoning"}), "id"
    )
    assert result.metadata.served_model == "backup"
    assert result.metadata.fallback_count == 1
    assert router.route("auto", "reasoning") == "primary"


def test_fallback_cycles_rejected():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            gateway_auth_enabled=False,
            gateway_models=[
                ModelMapping(model="a", provider="mock", fallback_model="b"),
                ModelMapping(model="b", provider="mock", fallback_model="a"),
            ],
        )


async def test_ollama_json_and_ndjson(payload):
    settings = Settings(_env_file=None, gateway_auth_enabled=False)
    data = {
        "message": {"content": "ok"},
        "done": True,
        "eval_count": 2,
        "prompt_eval_count": 3,
        "eval_duration": 100000000,
        "load_duration": 123,
    }

    def handler(request):
        body = json.loads(request.content)
        assert str(request.url).endswith("/api/chat")
        assert body["options"]["num_ctx"] == 1024
        if body["stream"]:
            return httpx.Response(200, content=(json.dumps(data) + "\n").encode())
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OllamaProvider(client, settings, "http://localhost:11434", None, ["q"])
        result = await provider.generate(ChatRequest(**payload), "q")
        assert result.usage.total_tokens == 5
        assert result.timing.eval_count == 2
        assert result.timing.load_duration_ns == 123
        chunks = [x async for x in provider.stream(ChatRequest(**payload), "q")]
        assert chunks[-1].timing.eval_duration_ns == 100000000


async def test_stream_bypasses_cache_and_fallback(payload):
    async with app_client(gateway_auth_enabled=False, gateway_cache_enabled=True) as (_, c):
        payload["temperature"] = 0
        await c.post("/v1/chat", json=payload)
        response = await c.post("/v1/chat/stream", json=payload)
        assert '"cache_status": "bypass"' in response.text
        assert '"fallback_count": 0' in response.text


async def test_fallback_attempt_budget_covers_both_models(payload):
    from app.core.trace import record_attempt

    class Broken(MockProvider):
        async def generate(self, *_):
            record_attempt()
            raise ProviderError()

    settings = Settings(
        _env_file=None,
        gateway_auth_enabled=False,
        gateway_max_provider_attempts=1,
        gateway_models=[
            ModelMapping(model="primary", provider="mock", fallback_model="backup"),
            ModelMapping(model="backup", provider="mock"),
        ],
    )
    service = ChatService(ProviderRouter(settings, {"mock": Broken(["m"])}), settings)
    with pytest.raises(ProviderError) as exc:
        await service.generate(ChatRequest(**{**payload, "model": "primary"}), "budget")
    assert exc.value.metadata.attempts == 1
    assert exc.value.metadata.fallback_count == 1
