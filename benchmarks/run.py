"""Entry point: python -m benchmarks.run --mode mock|real. No paid APIs."""

import argparse
import asyncio
import csv
import hashlib
import json
import socket
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

from benchmarks.client import request
from benchmarks.metrics import comparisons, summarize, variability
from benchmarks.runtime import KEY, ROOT, ResourceSampler, command, hardware, server
from benchmarks.workloads import DATA, repeated_prompts, tasks


class Run:
    def __init__(self, mode, config):
        self.config, self.mode = config, mode
        self.id = (
            datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            + "-"
            + mode
            + "-"
            + uuid.uuid4().hex[:6]
        )
        self.folder = ROOT / "benchmarks" / "results" / self.id
        self.folder.mkdir(parents=True)
        self.rows, self.resources, self.skipped = [], [], []
        self.ledgers = []
        self.manifest = {
            "run_id": self.id,
            "method_version": 2,
            "started_at": datetime.now(UTC).isoformat(),
            "mode": mode,
            "config": config,
            "hardware": hardware(),
            "git_commit": command(["git", "rev-parse", "HEAD"]),
            "git_dirty": bool(command(["git", "status", "--porcelain"])),
            "tasks_sha256": hashlib.sha256(DATA.read_bytes()).hexdigest(),
            "source_sha256": self.source_hash(),
            "status": "running",
            "cold_definition": (
                "Mock: first chat on fresh process/client; "
                "real: target absent from /api/ps; OS cache retained."
            ),
        }
        self.persist_manifest()
        files = [
            *ROOT.glob("app/**/*.py"),
            *ROOT.glob("benchmarks/**/*.py"),
            *ROOT.glob("benchmarks/configs/*.json"),
        ]
        snapshot = {str(p.relative_to(ROOT)): p.read_text() for p in sorted(files)}
        (self.folder / "source_snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False)
        )

    @staticmethod
    def source_hash():
        digest = hashlib.sha256()
        for path in sorted(
            [
                *ROOT.glob("app/**/*.py"),
                *ROOT.glob("benchmarks/**/*.py"),
                *ROOT.glob("benchmarks/configs/*.json"),
            ]
        ):
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def persist_manifest(self):
        (self.folder / "manifest.json").write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2)
        )

    def add(self, row, **labels):
        row.update(mode="simulated" if self.mode == "mock" else "real", **labels)
        self.rows.append(row)

    async def batch(
        self,
        client,
        url,
        payloads,
        labels,
        *,
        gateway=True,
        native=False,
        streaming=False,
        cold=False,
    ):
        semaphore = asyncio.Semaphore(labels["concurrency"])
        prefix = uuid.uuid4().hex[:10]

        async def one(index, payload):
            async with semaphore:
                row = await request(
                    client,
                    url,
                    payload,
                    f"{prefix}-{index}",
                    gateway=gateway,
                    native=native,
                    streaming=streaming,
                )
                phase = "cold" if cold else "warm"
                self.add(row, phase=phase, **labels)

        await asyncio.gather(*(one(i, p) for i, p in enumerate(payloads)))

    async def reconcile(self, client, upstream, labels):
        observed = (await client.get(upstream + "/stats")).json()
        matching = [
            r
            for r in self.rows
            if r.get("repeat") == labels.get("repeat")
            and r.get("experiment") == labels.get("experiment")
            and r.get("scenario") == labels.get("scenario")
            and r.get("strategy") == labels.get("strategy")
        ]
        if labels.get("scenario") != "connect":
            for row in matching:
                received = observed["attempts"].get(row["request_id"], 0)
                # Only compare IDs belonging to this fresh fixture process.
                if received or row.get("cache_status") == "hit":
                    assert received == row["upstream_attempts"], "Fixture/metadata mismatch"
        self.ledgers.append(
            {
                **labels,
                "server": observed,
                "note": "Connect refusals count as initiated attempts, not server receipts",
            }
        )

    def finish(self, status="complete"):
        self.manifest.update(
            status=status,
            finished_at=datetime.now(UTC).isoformat(),
            skipped=self.skipped,
            requests=len(self.rows),
        )
        self.persist_manifest()
        (self.folder / "requests.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.rows)
        )
        (self.folder / "fixture_ledgers.json").write_text(json.dumps(self.ledgers, indent=2))
        summaries = summarize(self.rows)
        (self.folder / "summary.json").write_text(
            json.dumps(summaries, ensure_ascii=False, indent=2)
        )
        (self.folder / "variability.json").write_text(
            json.dumps(variability(summaries), ensure_ascii=False, indent=2)
        )
        paired = comparisons(summaries)
        (self.folder / "comparisons.json").write_text(json.dumps(paired, indent=2))
        for name, records in [
            ("comparisons", paired),
            ("requests", self.rows),
            ("summary", summaries),
            ("resources", self.resources),
        ]:
            if records:
                keys = sorted({k for r in records for k in r})
                with (self.folder / (name + ".csv")).open("w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=keys)
                    writer.writeheader()
                    writer.writerows(records)
        from benchmarks.report import build_report

        build_report()
        print(
            json.dumps(
                {
                    "run_id": self.id,
                    "method_version": 2,
                    "requests": len(self.rows),
                    "status": status,
                    "report": "benchmarks/reports/index.html",
                },
                ensure_ascii=False,
            ),
            flush=True,
        )


def gateway_config(fixture, *, retries=0, fallback=False, cache=False, primary_url=None):
    return {
        "gateway_auth_enabled": True,
        "gateway_api_key": KEY,
        "gateway_models": [
            {
                "model": "fixture",
                "provider": "openai",
                "upstream_model": "primary",
                "fallback_model": "backup" if fallback else None,
            },
            {"model": "backup", "provider": "local", "upstream_model": "backup"},
            {"model": "small", "provider": "local", "upstream_model": "small"},
            {"model": "large", "provider": "local", "upstream_model": "large"},
        ],
        "openai_base_url": (primary_url or fixture) + "/v1",
        "openai_api_key": KEY,
        "local_base_url": fixture + "/v1",
        "upstream_max_retries": retries,
        "upstream_retry_base_seconds": 0.01,
        "upstream_read_timeout_seconds": 0.12,
        "upstream_connect_timeout_seconds": 0.1,
        "gateway_request_timeout_seconds": 3,
        "upstream_concurrency": 64,
        "gateway_rate_limit_requests": 100000,
        "gateway_cache_enabled": cache,
        "gateway_cache_ttl_seconds": 60,
        "gateway_task_routes": {
            "extract": "small",
            "arithmetic": "small",
            "reasoning": "large",
        },
    }


def payload(text="Hello Gateway", model="fixture", task_type=None):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": text}],
        "temperature": 0,
        "max_tokens": 64,
        "seed": 42,
    }
    if task_type:
        body["task_type"] = task_type
    return body


async def mock(run):
    config, n = run.config, run.config["requests"]
    for repeat in range(config["repeats"]):
        for concurrency in config["concurrency"]:
            labels = dict(
                experiment="A",
                scenario="fixed_delay",
                model="fixture",
                concurrency=concurrency,
                repeat=repeat,
            )
            async with server("fixture", {"delay_ms": config["delay_ms"]}) as (upstream, _):
                async with server("gateway", gateway_config(upstream)) as (gateway, pid):
                    monitor = ResourceSampler(pid)
                    sampling = asyncio.create_task(monitor.run())
                    try:
                        async with httpx.AsyncClient(
                            trust_env=False,
                            timeout=5,
                            limits=httpx.Limits(max_connections=100),
                            headers={"Authorization": "Bearer " + KEY},
                        ) as c:
                            strategies = (
                                ["direct", "gateway"]
                                if repeat % 2 == 0
                                else ["gateway", "direct"]
                            )
                            for strategy in strategies:
                                url = upstream if strategy == "direct" else gateway
                                body = payload(
                                    model="primary" if strategy == "direct" else "fixture"
                                )
                                await run.batch(
                                    c,
                                    url,
                                    [body],
                                    {**labels, "strategy": strategy},
                                    gateway=strategy == "gateway",
                                    cold=True,
                                )
                                await asyncio.gather(
                                    *(
                                        request(
                                            c,
                                            url,
                                            body,
                                            f"warmup-{uuid.uuid4().hex[:8]}-{i}",
                                            gateway=strategy == "gateway",
                                        )
                                        for i in range(concurrency)
                                    )
                                )
                                await run.batch(
                                    c,
                                    url,
                                    [body] * n,
                                    {**labels, "strategy": strategy},
                                    gateway=strategy == "gateway",
                                )
                                await run.reconcile(
                                    c, upstream, {**labels, "strategy": strategy}
                                )
                    finally:
                        monitor.stop.set()
                        await sampling
                        run.resources.extend({**x, **labels} for x in monitor.samples)
        for fault in ("503", "429", "timeout", "connect"):
            for strategy in ("none", "retry", "retry_fallback"):
                labels = dict(
                    experiment="B",
                    scenario=fault,
                    strategy=strategy,
                    model="fixture",
                    concurrency=5,
                    repeat=repeat,
                )
                async with server("fixture", {"delay_ms": 5, "fault": fault}) as (upstream, _):
                    with socket.socket() as closed:
                        closed.bind(
                            ("127.0.0.1", 0)
                        )  # Reserved but not listening: deterministic connect refusal.
                        bad = (
                            f"http://127.0.0.1:{closed.getsockname()[1]}"
                            if fault == "connect"
                            else None
                        )
                        cfg = gateway_config(
                            upstream,
                            retries=0 if strategy == "none" else 2,
                            fallback=strategy == "retry_fallback",
                            primary_url=bad,
                        )
                        async with server("gateway", cfg) as (gateway, _):
                            async with httpx.AsyncClient(
                                trust_env=False,
                                timeout=5,
                                headers={"Authorization": "Bearer " + KEY},
                            ) as c:
                                await run.batch(
                                    c,
                                    gateway,
                                    [payload("Failure recovery public example")],
                                    labels,
                                    cold=True,
                                )
                                await run.batch(
                                    c,
                                    gateway,
                                    [payload("Failure recovery public example")] * n,
                                    labels,
                                )
                                await run.reconcile(c, upstream, labels)
        for rate in config["cache_repeat_rates"]:
            prompts = repeated_prompts(n, rate, config["seed"] + repeat)
            for enabled in (False, True):
                labels = dict(
                    experiment="C",
                    scenario=f"repeat_{rate:.0%}",
                    strategy="cache_on" if enabled else "cache_off",
                    model="fixture",
                    concurrency=1,
                    repeat=repeat,
                )
                async with server("fixture", {"delay_ms": config["delay_ms"]}) as (upstream, _):
                    async with server("gateway", gateway_config(upstream, cache=enabled)) as (
                        gateway,
                        _,
                    ):
                        async with httpx.AsyncClient(
                            trust_env=False,
                            timeout=5,
                            headers={"Authorization": "Bearer " + KEY},
                        ) as c:
                            await run.batch(
                                c, gateway, [payload(prompts[0])], labels, cold=True
                            )
                            await run.batch(
                                c, gateway, [payload(t) for t in prompts[1:]], labels
                            )
                            await run.reconcile(c, upstream, labels)
        # Exercise task-routing contracts, but never publish fixture echo as LLM accuracy.
        async with server("fixture", {"delay_ms": 5}) as (upstream, _):
            async with server("gateway", gateway_config(upstream)) as (gateway, _):
                async with httpx.AsyncClient(
                    trust_env=False, timeout=5, headers={"Authorization": "Bearer " + KEY}
                ) as c:
                    for strategy, model in [
                        ("all_0.5b", "small"),
                        ("all_1.5b", "large"),
                        ("task_route", "auto"),
                    ]:
                        for index, task in enumerate(tasks(config["seed"] + repeat)):
                            row = await request(
                                c,
                                gateway,
                                payload(task["prompt"], model, task["task_type"]),
                                f"d-{uuid.uuid4().hex[:6]}-{index}",
                            )
                            row.update(
                                task_id=task["id"], correct=None, expected=task["answer"]
                            )
                            run.add(
                                row,
                                experiment="D",
                                scenario="contract_only",
                                strategy=strategy,
                                model="simulated",
                                concurrency=1,
                                repeat=repeat,
                                phase="cold" if index == 0 else "warm",
                            )
                    await run.batch(
                        c,
                        gateway,
                        [payload("Streaming contract")] * 3,
                        dict(
                            experiment="E",
                            scenario="sse_contract_only",
                            strategy="gateway",
                            model="simulated",
                            concurrency=1,
                            repeat=repeat,
                        ),
                        streaming=True,
                    )
        print(f"Mock repeat {repeat + 1}/{config['repeats']} finished", flush=True)
    run.skipped.extend(
        [
            {
                "experiment": "D",
                "mode": "real",
                "reason": "Run the separate real benchmark for model accuracy",
            },
            {
                "experiment": "E",
                "mode": "real",
                "reason": "Mock has no actual inference token/GPU measurements",
            },
        ]
    )


async def main(args):
    config_path = Path(args.config or ROOT / "benchmarks" / "configs" / (args.mode + ".json"))
    config = json.loads(await asyncio.to_thread(config_path.read_text))
    run = Run(args.mode, config)
    try:
        if args.mode == "mock":
            await mock(run)
            from benchmarks.verify import verify_mock

            run.manifest["behavioral_checks"] = verify_mock(run.rows)
        else:
            from benchmarks.real import real

            await real(run, args.ollama_url)
    except Exception as exc:
        run.skipped.append(
            {"experiment": "run", "reason": type(exc).__name__ + ": " + str(exc)[:300]}
        )
        run.finish("failed")
        raise
    else:
        run.finish("partial" if args.mode == "real" and run.skipped else "complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["mock", "real"], default="mock")
    parser.add_argument("--config")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    asyncio.run(main(parser.parse_args()))
