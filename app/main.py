from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import chat, health, models
from app.core.config import Settings
from app.domain.errors import GatewayError
from app.providers.local import LocalProvider
from app.providers.mock import MockProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.router import ProviderRouter
from app.services.chat_service import ChatService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

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
            providers = {"mock": provider}
            for name, adapter, base_url, key in [
                (
                    "openai",
                    OpenAICompatibleProvider,
                    settings.openai_base_url,
                    settings.openai_api_key,
                ),
                ("local", LocalProvider, settings.local_base_url, settings.local_api_key),
            ]:
                if any(m.enabled and m.provider == name for m in settings.gateway_models):
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

    app = FastAPI(title="LLM Gateway Service", version="0.1.0", lifespan=lifespan)
    provider = MockProvider(
        [m.upstream_model for m in settings.gateway_models if m.provider == "mock"],
        settings.mock_chunk_delay_seconds,
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        request.state.request_id = uuid4().hex
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(GatewayError)
    async def gateway_error(request: Request, exc: GatewayError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "request_id": request.state.request_id,
                }
            },
        )

    app.include_router(chat.router)
    app.include_router(models.router)
    app.include_router(health.router)
    return app
