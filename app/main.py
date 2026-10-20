from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import chat, health, models
from app.core.config import Settings
from app.domain.errors import GatewayError
from app.providers.mock import MockProvider
from app.providers.router import ProviderRouter
from app.services.chat_service import ChatService


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="LLM Gateway Service", version="0.1.0")
    provider = MockProvider(
        [m.upstream_model for m in settings.gateway_models if m.provider == "mock"],
        settings.mock_chunk_delay_seconds,
    )
    app.state.router = ProviderRouter(settings, {"mock": provider})
    app.state.chat = ChatService(app.state.router)

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
