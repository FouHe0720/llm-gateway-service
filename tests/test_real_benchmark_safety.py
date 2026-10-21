import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

import benchmarks.real as driver


async def test_failed_baseline_never_escalates_and_models_are_unloaded(monkeypatch):
    calls, unloads = [], []
    config = dict(
        models=["qwen2.5:0.5b", "qwen2.5:1.5b"],
        concurrency=[1, 2],
        context_length=1024,
        repeats=1,
        seed=42,
        requests=4,
    )

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            body = (
                {"models": [{"name": m} for m in config["models"]]}
                if url.endswith("/api/tags")
                else {"version": "fixture"}
            )
            return SimpleNamespace(json=lambda: body)

    class Sampler:
        def __init__(self, *args, **kwargs):
            self.stop, self.samples, self.context = asyncio.Event(), [], {}

        async def run(self):
            await self.stop.wait()

    class Run:
        def __init__(self):
            self.config, self.rows, self.manifest, self.skipped, self.resources = (
                config,
                [],
                {},
                [],
                [],
            )

        def persist_manifest(self):
            pass

        def add(self, row, **labels):
            self.rows.append({**row, **labels})

        async def batch(self, *args, **kwargs):
            raise AssertionError("Failed cold request must not launch warm requests")

    @asynccontextmanager
    async def server(*args):
        yield "http://gateway.test", 0

    async def fail_request(*args, **kwargs):
        calls.append(args[1])
        return {"success": False}

    async def unload(*args):
        unloads.append(args[-1])

    async def guard(*args):
        pass

    monkeypatch.setattr(driver.httpx, "AsyncClient", lambda **kwargs: Client())
    monkeypatch.setattr(driver, "ResourceSampler", Sampler)
    monkeypatch.setattr(driver, "server", server)
    monkeypatch.setattr(driver, "request", fail_request)
    monkeypatch.setattr(driver, "unload", unload)
    monkeypatch.setattr(driver, "guard", guard)
    monkeypatch.setattr(driver, "tasks", lambda seed: [])
    run = Run()
    await driver.real(run, "http://localhost:11434")
    assert len(calls) == 4  # 2 models × 2 paths; no concurrency-2 trials.
    assert sum("no escalation" in x["reason"] for x in run.skipped) == 2
    assert unloads[-1] == config["models"]
    config["concurrency"] = [2, 1]
    with pytest.raises(ValueError):
        await driver.real(Run(), "http://localhost:11434")
