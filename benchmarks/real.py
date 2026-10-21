import asyncio
import uuid
from urllib.parse import urlsplit

import httpx

from benchmarks.client import request
from benchmarks.run import payload
from benchmarks.runtime import KEY, ResourceSampler, available_memory_mib, gpu_snapshot, server
from benchmarks.workloads import grade, tasks


async def guard(config):
    available = available_memory_mib()
    if available is not None and available < config["min_available_memory_mib"]:
        raise RuntimeError("Safety stop: low available RAM; reduce output/concurrency")
    gpu = await asyncio.to_thread(gpu_snapshot)
    if gpu and gpu["used_mib"] / gpu["total_mib"] >= config["gpu_stop_ratio"]:
        raise RuntimeError(
            "Safety stop: GPU memory exceeds configured threshold; no further requests launched"
        )


async def loaded(client, url):
    response = await client.get(url + "/api/ps")
    response.raise_for_status()
    return {m.get("name", m.get("model")) for m in response.json().get("models", [])}


async def unload(client, url, models):
    for model in models:
        response = await client.post(
            url + "/api/generate", json={"model": model, "keep_alive": 0}
        )
        response.raise_for_status()
    async with asyncio.timeout(15):
        for _ in range(60):
            if not (set(models) & await loaded(client, url)):
                return
            await asyncio.sleep(0.2)
        raise RuntimeError("Could not confirm model unload; cold sample refused")


async def real(run, url):
    if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Real benchmark only accepts localhost Ollama; no cloud calls")
    config = run.config
    if set(config["models"]) != {"qwen2.5:0.5b", "qwen2.5:1.5b"}:
        raise ValueError(
            "This resource-bounded protocol requires exactly Qwen2.5 0.5B and 1.5B"
        )
    if max(config["concurrency"]) > 2 or config["context_length"] != 1024:
        raise ValueError("4GB protocol caps client concurrency at 2 and context at 1024")
    async with httpx.AsyncClient(
        trust_env=False, timeout=90, headers={"Authorization": "Bearer " + KEY}
    ) as client:
        try:
            version = (await client.get(url + "/api/version")).json()
            tags = (await client.get(url + "/api/tags")).json()["models"]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            run.skipped.append(
                {
                    "experiment": "D/E",
                    "mode": "real",
                    "reason": "Ollama unavailable: " + type(exc).__name__,
                }
            )
            return
        available = {m["name"]: m for m in tags}
        missing = [m for m in config["models"] if m not in available]
        run.manifest["ollama_version"] = version
        run.manifest["models"] = {
            name: available[name] for name in config["models"] if name in available
        }
        if missing:
            run.skipped.append(
                {
                    "experiment": "D/E",
                    "mode": "real",
                    "reason": "Missing models: "
                    + ", ".join(missing)
                    + ". Pull them explicitly from the official Ollama registry.",
                }
            )
            return
        run.manifest["ollama_process_policy"] = {
            "required": "OLLAMA_MAX_LOADED_MODELS=1, OLLAMA_NUM_PARALLEL=1",
            "context": config["context_length"],
            "sampling": "temperature=0, seed=42, max_tokens=64",
            "note": "Client concurrency=2 measures queueing with OLLAMA_NUM_PARALLEL=1.",
        }
        run.persist_manifest()
        cfg = {
            "gateway_api_key": KEY,
            "gateway_models": [
                {
                    "model": "qwen-0.5b",
                    "provider": "ollama",
                    "upstream_model": config["models"][0],
                },
                {
                    "model": "qwen-1.5b",
                    "provider": "ollama",
                    "upstream_model": config["models"][1],
                },
            ],
            "ollama_base_url": url,
            "ollama_context_length": config["context_length"],
            "upstream_max_retries": 0,
            "upstream_concurrency": 2,
            "gateway_request_timeout_seconds": 80,
            "upstream_read_timeout_seconds": 75,
            "gateway_rate_limit_requests": 100000,
            "gateway_cache_enabled": False,
            "gateway_task_routes": {
                "extract": "qwen-0.5b",
                "arithmetic": "qwen-0.5b",
                "reasoning": "qwen-1.5b",
            },
        }
        async with server("gateway", cfg) as (gateway, pid):
            sampler = ResourceSampler(pid, gpu=True)
            sampling = asyncio.create_task(sampler.run())
            try:
                for repeat in range(config["repeats"]):
                    for strategy, alias in [
                        ("all_0.5b", "qwen-0.5b"),
                        ("all_1.5b", "qwen-1.5b"),
                        ("task_route", "auto"),
                    ]:
                        await unload(client, url, config["models"])
                        for index, task in enumerate(tasks(config["seed"] + repeat)):
                            await guard(config)
                            selected = (
                                alias
                                if alias != "auto"
                                else cfg["gateway_task_routes"][task["task_type"]]
                            )
                            sampler.context = {
                                "experiment": "D",
                                "model": selected,
                                "strategy": strategy,
                                "repeat": repeat,
                            }
                            native_model = config["models"][0 if selected == "qwen-0.5b" else 1]
                            resident = native_model in await loaded(client, url)
                            row = await request(
                                client,
                                gateway,
                                payload(task["prompt"], alias, task["task_type"]),
                                f"d-{uuid.uuid4().hex[:8]}-{index}",
                            )
                            row.update(
                                task_id=task["id"],
                                expected=task["answer"],
                                correct=row["success"] and grade(row["answer"], task["answer"]),
                                resident_before=resident,
                                task_type=task["task_type"],
                            )
                            run.add(
                                row,
                                experiment="D",
                                scenario="labeled_tasks",
                                strategy=strategy,
                                model=alias,
                                concurrency=1,
                                repeat=repeat,
                                phase="warm" if resident else "cold",
                            )
                    for index, model in enumerate(config["models"]):
                        alias = "qwen-0.5b" if index == 0 else "qwen-1.5b"
                        for concurrency in config["concurrency"]:
                            order = (
                                ["direct", "gateway"]
                                if repeat % 2 == 0
                                else ["gateway", "direct"]
                            )
                            for strategy in order:
                                await unload(client, url, config["models"])
                                await guard(config)
                                target = url if strategy == "direct" else gateway
                                body = payload(
                                    "Briefly explain the purpose of request IDs.",
                                    model if strategy == "direct" else alias,
                                )
                                sampler.context = {
                                    "experiment": "E",
                                    "model": model,
                                    "strategy": strategy,
                                    "concurrency": concurrency,
                                    "repeat": repeat,
                                }
                                labels = dict(
                                    experiment="E",
                                    scenario="ollama_sse",
                                    strategy=strategy,
                                    model=model,
                                    concurrency=concurrency,
                                    repeat=repeat,
                                )
                                # Record unloaded-model cold requests separately.
                                cold = await request(
                                    client,
                                    target,
                                    body,
                                    f"cold-{uuid.uuid4().hex[:8]}-0",
                                    gateway=strategy == "gateway",
                                    native=strategy == "direct",
                                    streaming=True,
                                )
                                run.add(cold, phase="cold", **labels)
                                if not cold["success"]:
                                    run.skipped.append(
                                        {
                                            "experiment": "E",
                                            "reason": model + "/" + strategy + ": cold failure",
                                        }
                                    )
                                    continue
                                await guard(config)
                                await run.batch(
                                    client,
                                    target,
                                    [body] * config["requests"],
                                    labels,
                                    gateway=strategy == "gateway",
                                    native=strategy == "direct",
                                    streaming=True,
                                )
                    print(f"Real repeat {repeat + 1}/{config['repeats']} finished", flush=True)
            finally:
                sampler.stop.set()
                await sampling
                run.resources.extend({**x, "mode": "real"} for x in sampler.samples)
                await unload(client, url, config["models"])
