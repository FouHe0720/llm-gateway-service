async def test_health_and_models(client):
    assert (await client.get("/health")).json() == {"status": "ok"}
    assert (await client.get("/v1/models")).json() == {
        "models": [{"model": "mock-echo", "provider": "mock", "simulated_stream": True}]
    }
    assert (await client.get("/docs")).status_code == 200
