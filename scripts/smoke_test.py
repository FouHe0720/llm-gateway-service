import argparse
import asyncio
import json
import os

import httpx


async def smoke(base_url: str) -> None:
    """Offline Mock contract smoke test. Never select a real model automatically."""
    key = os.environ.get("GATEWAY_API_KEY")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    async with httpx.AsyncClient(
        base_url=base_url, headers=headers, timeout=10, trust_env=False
    ) as c:
        assert (await c.get("/health")).json() == {"status": "ok"}
        models = (await c.get("/v1/models")).json()["models"]
        assert any(m["model"] == "mock-echo" and m["provider"] == "mock" for m in models)
        payload = {
            "model": "mock-echo",
            "messages": [{"role": "user", "content": "Hello Gateway"}],
        }
        response = await c.post("/v1/chat", json=payload, headers={"X-Request-ID": "demo-chat"})
        response.raise_for_status()
        assert response.json()["answer"] == "[mock] Hello Gateway"
        print("CHAT", json.dumps(response.json(), ensure_ascii=False), flush=True)
        kinds, deltas = [], []
        async with c.stream("POST", "/v1/chat/stream", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line:
                    print(line, flush=True)
                if line.startswith("event: "):
                    kinds.append(line[7:])
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if "delta" in data:
                        deltas.append(data["delta"])
        assert kinds[0] == "start" and kinds[-1] == "done" and "error" not in kinds
        assert "".join(deltas) == "[mock] Hello Gateway"
        assert (
            await c.post("/v1/chat", json={**payload, "model": "missing"})
        ).status_code == 404
        assert (await c.post("/v1/chat", json={**payload, "messages": []})).status_code == 422
        metrics = (await c.get("/metrics")).json()
        assert metrics["requests_total"]["/v1/chat"] >= 3
        print("METRICS", json.dumps(metrics), flush=True)
        print("Mock smoke passed: health, models, chat, SSE, 404, 422, metrics", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    asyncio.run(smoke(parser.parse_args().base_url))
