import asyncio
import json
import random
import socket
import sys
from collections import Counter
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.config import Settings
from app.main import create_app


def fixture_app(config):
    app = FastAPI()
    attempts, active, peak = Counter(), 0, 0
    events = []

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/stats")
    async def stats():
        return {"attempts": dict(attempts), "active": active, "peak": peak, "events": events}

    @app.post("/v1/chat/completions")
    async def completion(request: Request):
        nonlocal active, peak
        body = await request.json()
        rid = request.headers.get("x-request-id", "unknown")
        attempts[rid] += 1
        attempt = attempts[rid]
        index = int(rid.rsplit("-", 1)[-1]) if rid.rsplit("-", 1)[-1].isdigit() else 0
        model = body["model"]
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(config.get("delay_ms", 20) / 1000)
            fault = config.get("fault")
            status = 200
            if model != "backup" and index % 5 == 0:
                if fault in {"503", "429"} and attempt == 1:
                    status = int(fault)
                if fault == "timeout":
                    await asyncio.sleep(config.get("timeout_delay_ms", 250) / 1000)
            events.append(
                {"request_id": rid, "model": model, "attempt": attempt, "status": status}
            )
            if status != 200:
                return JSONResponse({"error": "injected"}, status_code=status)
            answer = "[fixture] " + body["messages"][-1]["content"]
            if body.get("stream"):

                async def stream():
                    for offset in range(0, len(answer), 8):
                        await asyncio.sleep(0.01)
                        yield (
                            "data: "
                            + json.dumps(
                                {
                                    "choices": [
                                        {"delta": {"content": answer[offset : offset + 8]}}
                                    ]
                                }
                            )
                            + "\n\n"
                        )
                    yield "data: [DONE]\n\n"

                return StreamingResponse(stream(), media_type="text/event-stream")
            return {"choices": [{"message": {"content": answer}}]}
        finally:
            active -= 1

    return app


if __name__ == "__main__":
    kind, path, fd = sys.argv[1:]
    config = json.loads(Path(path).read_text())
    random.seed(config.pop("_benchmark_seed", 42))
    app = (
        fixture_app(config)
        if kind == "fixture"
        else create_app(Settings(_env_file=None, **config))
    )
    inherited = socket.socket(fileno=int(fd))
    inherited.setblocking(False)
    assert inherited.family == socket.AF_INET
    inherited.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    runner = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning"))
    asyncio.run(runner.serve(sockets=[inherited]))
