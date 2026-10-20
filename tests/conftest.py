import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
async def client():
    settings = Settings(_env_file=None, gateway_auth_enabled=False, mock_chunk_delay_seconds=0)
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as value:
            yield value


@pytest.fixture
def payload():
    return {"model": "mock-echo", "messages": [{"role": "user", "content": "Hello Gateway"}]}
