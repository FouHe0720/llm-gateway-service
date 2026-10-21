"""Small native 0.5B cache trial, callable separately or after D/E."""

import argparse
import asyncio
import json
import uuid
from urllib.parse import urlsplit

import httpx

from benchmarks.client import request
from benchmarks.real import guard, unload
from benchmarks.run import Run, payload
from benchmarks.runtime import KEY, ROOT, ResourceSampler, server
from benchmarks.workloads import repeated_prompts


async def real_cache(run, url):
    if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Real cache benchmark requires localhost Ollama")
    config = run.config
    model = "qwen2.5:0.5b"
    async with httpx.AsyncClient(
        trust_env=False, timeout=90, headers={"Authorization": "Bearer " + KEY}
    ) as client:
        available = (await client.get(url + "/api/tags")).json()["models"]
        tag = next((m for m in available if m["name"] == model), None)
        if tag is None:
            run.skipped.append(
                {"experiment": "C", "mode": "real", "reason": "qwen2.5:0.5b not installed"}
            )
            return
        run.manifest.setdefault("models", {})[model] = tag
        run.manifest["cache_real_protocol"] = {
            "requests": 10,
            "repeat_rates": [0, 0.5, 0.9],
            "max_tokens": 16,
            "context": 1024,
            "concurrency": 1,
            "model": model,
        }
        run.persist_manifest()
        for repeat in range(config["repeats"]):
            for rate in (0, 0.5, 0.9):
                prompts = repeated_prompts(10, rate, config["seed"] + repeat)
                for enabled in (False, True):
                    await unload(client, url, [model])
                    await guard(config)
                    cfg = {
                        "gateway_api_key": KEY,
                        "gateway_models": [
                            {
                                "model": "qwen-cache",
                                "provider": "ollama",
                                "upstream_model": model,
                            }
                        ],
                        "ollama_base_url": url,
                        "ollama_context_length": 1024,
                        "upstream_max_retries": 0,
                        "upstream_concurrency": 1,
                        "gateway_request_timeout_seconds": 80,
                        "upstream_read_timeout_seconds": 75,
                        "gateway_rate_limit_requests": 100000,
                        "gateway_cache_enabled": enabled,
                        "gateway_cache_ttl_seconds": 60,
                    }
                    labels = dict(
                        experiment="C",
                        scenario=f"repeat_{rate:.0%}",
                        strategy="cache_on" if enabled else "cache_off",
                        model=model,
                        concurrency=1,
                        repeat=repeat,
                    )
                    async with server("gateway", cfg) as (gateway, pid):
                        sampler = ResourceSampler(pid, gpu=True)
                        sampling = asyncio.create_task(sampler.run())
                        try:
                            actual_calls = 0
                            confirmed_calls = 0
                            for index, text in enumerate(prompts):
                                body = payload(
                                    "Repeat this label without explanation: " + text,
                                    "qwen-cache",
                                )
                                body["max_tokens"] = 16
                                row = await request(
                                    client,
                                    gateway,
                                    body,
                                    f"cache-{uuid.uuid4().hex[:8]}-{index}",
                                )
                                actual_calls += row["upstream_attempts"]
                                confirmed_calls += int(
                                    row["success"] and row["output_tokens"] is not None
                                )
                                run.add(row, phase="cold" if index == 0 else "warm", **labels)
                            expected = max(1, round(10 * (1 - rate))) if enabled else 10
                            if all(r["success"] for r in run.rows[-10:]):
                                assert confirmed_calls == actual_calls
                                assert actual_calls == expected, (
                                    "Real cache call accounting mismatch"
                                )
                        finally:
                            sampler.stop.set()
                            await sampling
                            run.resources.extend(
                                {**r, **labels, "mode": "real"} for r in sampler.samples
                            )
                    print(
                        f"Real cache repeat {repeat + 1}, {rate:.0%}, enabled={enabled}",
                        flush=True,
                    )
        await unload(client, url, [model])


async def main(url):
    config = json.loads((ROOT / "benchmarks/configs/real.json").read_text())
    run = Run("real", config)
    try:
        await real_cache(run, url)
    except Exception as exc:
        run.skipped.append(
            {"experiment": "C", "reason": type(exc).__name__ + ": " + str(exc)[:200]}
        )
        run.finish("failed")
        raise
    else:
        run.finish("partial" if run.skipped else "complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    asyncio.run(main(parser.parse_args().ollama_url))
