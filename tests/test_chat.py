import pytest


async def test_mock_chat(client, payload):
    response = await client.post("/v1/chat", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "[mock] Hello Gateway"
    assert body["usage"] is None
    assert body["model"] == "mock-echo"
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert body["latency_ms"] >= 0


@pytest.mark.parametrize(
    "field,value",
    [("messages", []), ("temperature", 3), ("top_p", 0), ("max_tokens", -1)],
)
async def test_invalid_input(client, payload, field, value):
    payload[field] = value
    assert (await client.post("/v1/chat", json=payload)).status_code == 422


async def test_unknown_model(client, payload):
    payload["model"] = "missing"
    response = await client.post("/v1/chat", json=payload)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "model_not_found"
