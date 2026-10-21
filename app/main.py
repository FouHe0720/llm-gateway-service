from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from app.api.errors import ERROR_RESPONSES, gateway_error, http_error, validation_error
from app.api.routes import chat, health, metrics, models
from app.core.config import Settings
from app.core.logging import configure_logging
from app.domain.errors import GatewayError
from app.infra.metrics import Metrics
from app.middleware.rate_limit import SlidingWindowLimiter
from app.middleware.request_id import RequestContextMiddleware
from app.providers.base import BaseLLMProvider
from app.providers.local import LocalProvider
from app.providers.mock import MockProvider
from app.providers.ollama import OllamaProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.router import ProviderRouter
from app.services.chat_service import ChatService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        timeout = httpx.Timeout(
            settings.upstream_read_timeout_seconds,
            connect=settings.upstream_connect_timeout_seconds,
        )
        async with httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=settings.upstream_concurrency),
            follow_redirects=False,
            trust_env=False,
        ) as client:
            providers: dict[str, BaseLLMProvider] = {"mock": provider}
            for name, adapter, base_url, key in [
                (
                    "openai",
                    OpenAICompatibleProvider,
                    settings.openai_base_url,
                    settings.openai_api_key,
                ),
                ("local", LocalProvider, settings.local_base_url, settings.local_api_key),
                ("ollama", OllamaProvider, settings.ollama_base_url, None),
            ]:
                if any(m.enabled and m.provider == name for m in settings.gateway_models):
                    assert base_url is not None  # Settings validated enabled provider URLs.
                    providers[name] = adapter(
                        client,
                        settings,
                        base_url,
                        key.get_secret_value() if key else None,
                        [
                            m.upstream_model
                            for m in settings.gateway_models
                            if m.provider == name
                        ],
                    )
            app.state.router = ProviderRouter(settings, providers)
            app.state.chat = ChatService(app.state.router, settings)
            yield

    app = FastAPI(
        title="LLM Gateway Service",
        version="0.1.0",
        lifespan=lifespan,
        responses=ERROR_RESPONSES,
    )
    app.state.settings = settings
    app.state.metrics = Metrics()
    app.state.limiter = SlidingWindowLimiter(
        settings.gateway_rate_limit_requests, settings.gateway_rate_limit_window_seconds
    )
    app.add_middleware(
        RequestContextMiddleware,
        metrics=app.state.metrics,
        max_body_bytes=settings.gateway_max_body_bytes,
    )
    app.add_exception_handler(GatewayError, gateway_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(HTTPException, http_error)
    provider = MockProvider(
        [m.upstream_model for m in settings.gateway_models if m.provider == "mock"],
        settings.mock_chunk_delay_seconds,
    )

    app.include_router(chat.router)
    app.include_router(models.router)
    app.include_router(health.router)
    app.include_router(metrics.router)
    return app
