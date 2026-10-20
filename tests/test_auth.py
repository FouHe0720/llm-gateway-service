import pytest
from pydantic import ValidationError

from app.core.config import ModelMapping, Settings
from tests.helpers import app_client

TEST_KEY = "fixture-key-for-local-tests"


@pytest.mark.parametrize("header", [None, "Bearer wrong", "Basic invalid"])
async def test_unauthorized(header, payload):
    async with app_client(gateway_api_key=TEST_KEY) as (_, client):
        headers = {"Authorization": header} if header else {}
        response = await client.post("/v1/chat", json=payload, headers=headers)
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json()["error"]["code"] == "unauthorized"
        assert (await client.get("/health")).status_code == 200
        assert (await client.get("/metrics")).status_code == 401


async def test_correct_key_and_rate_limit_are_distinct(payload):
    async with app_client(gateway_api_key=TEST_KEY, gateway_rate_limit_requests=1) as (
        _,
        client,
    ):
        headers = {"Authorization": f"Bearer {TEST_KEY}"}
        assert (await client.post("/v1/chat", json=payload, headers=headers)).status_code == 200
        response = await client.post("/v1/chat", json=payload, headers=headers)
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "rate_limited"
        assert int(response.headers["retry-after"]) >= 1


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"gateway_auth_enabled": False, "gateway_environment": "production"},
        {
            "gateway_auth_enabled": False,
            "gateway_models": [ModelMapping(model="local", provider="local")],
        },
        {"gateway_api_key": "short"},
        {
            "gateway_api_key": TEST_KEY,
            "gateway_models": [ModelMapping(model="x", provider="openai")],
        },
        {
            "gateway_api_key": TEST_KEY,
            "local_base_url": "http://remote.test/v1",
            "gateway_models": [ModelMapping(model="x", provider="local")],
        },
    ],
)
def test_invalid_or_unsafe_startup_config(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


async def test_enabled_local_mapping_does_not_expose_connection_info():
    async with app_client(
        gateway_api_key=TEST_KEY,
        local_api_key="private-upstream-fixture",
        gateway_models=[
            ModelMapping(model="public-name", provider="local", upstream_model="raw")
        ],
    ) as (_, client):
        response = await client.get(
            "/v1/models", headers={"Authorization": f"Bearer {TEST_KEY}"}
        )
        assert response.json()["models"][0]["model"] == "public-name"
        assert "private-upstream" not in response.text
        assert "127.0.0.1" not in response.text
        assert "raw" not in response.text


def test_startup_validation_does_not_print_credentials():
    secret = "private-fixture-that-must-not-appear-in-startup-errors"
    with pytest.raises(ValidationError) as exc:
        Settings(
            _env_file=None,
            gateway_api_key=secret,
            gateway_models=[ModelMapping(model="online", provider="openai")],
            openai_api_key=secret,
            openai_base_url="invalid-url",
        )
    assert secret not in str(exc.value)
