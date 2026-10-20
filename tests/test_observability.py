import json
import logging

import pytest

from app.core.logging import JSONFormatter
from app.middleware.rate_limit import SlidingWindowLimiter
from tests.helpers import app_client


async def test_request_id_echo_and_sanitization(client, payload):
    response = await client.post("/v1/chat", json=payload, headers={"X-Request-ID": "demo-123"})
    assert response.headers["x-request-id"] == "demo-123"
    assert response.json()["request_id"] == "demo-123"
    response = await client.get("/health", headers={"X-Request-ID": "unsafe id"})
    assert response.headers["x-request-id"] != "unsafe id"


@pytest.mark.parametrize(
    "change",
    [
        {"messages": [{"role": "root", "content": "sensitive-prompt"}]},
        {"messages": [{"role": "user", "content": "   "}]},
        {"max_tokens": True},
        {"max_tokens": "123"},
        {"extra": "sensitive-prompt"},
    ],
)
async def test_validation_error_is_uniform_and_private(client, payload, change):
    payload.update(change)
    response = await client.post("/v1/chat", json=payload)
    assert response.status_code == 422
    assert "sensitive-prompt" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


async def test_body_limit_before_json_parse(client):
    response = await client.post("/v1/chat", content=b"x" * 140_000)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


async def test_metrics_cardinality_and_failures(client, payload):
    await client.post("/v1/chat", json=payload)
    await client.get("/unknown/user-123")
    await client.get("/unknown/user-456")
    metrics = (await client.get("/metrics")).json()
    assert metrics["requests_total"]["/v1/chat"] == 1
    assert metrics["requests_total"]["other"] == 2
    assert metrics["failures_total"]["other"] == 2
    assert metrics["latency_ms"]["cumulative_buckets"]["+Inf"] == 3
    assert "user-123" not in json.dumps(metrics)


async def test_logs_contain_id_but_not_prompt_or_key(payload):
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(JSONFormatter().format(record))

    handler = Capture()
    logger = logging.getLogger("gateway")
    logger.addHandler(handler)
    try:
        async with app_client(gateway_auth_enabled=False) as (_, client):
            await client.post(
                "/v1/chat", json=payload, headers={"X-Request-ID": "trace-log-test"}
            )
        text = "\n".join(records)
        assert "trace-log-test" in text
        assert "Hello Gateway" not in text
        assert json.loads(records[-1])["event"] == "request_complete"
    finally:
        logger.removeHandler(handler)


def test_rate_window_expires(monkeypatch):
    now = 0.0
    monkeypatch.setattr("app.middleware.rate_limit.monotonic", lambda: now)
    limiter = SlidingWindowLimiter(1, 10)
    assert limiter.consume() is None
    assert limiter.consume() == 10
    now = 10.1
    assert limiter.consume() is None
