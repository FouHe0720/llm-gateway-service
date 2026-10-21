"""Own subprocesses, sample hardware without publishing host names or machine paths."""

import asyncio
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

import httpx

ROOT = Path(__file__).resolve().parents[1]
KEY = "benchmark-local-fixture-key"


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def gpu_snapshot():
    value = command(
        [
            "nvidia-smi",
            "--query-gpu=memory.used,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        ]
    )
    if not value:
        return None
    try:
        used, total, utilization = value.splitlines()[0].split(",")
        return {
            "used_mib": float(used),
            "total_mib": float(total),
            "utilization_pct": float(utilization),
        }
    except ValueError:
        return None


def available_memory_mib():
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 1024
    return None


def hardware():
    cpu = next(
        (
            line.split(":", 1)[1].strip()
            for line in Path("/proc/cpuinfo").read_text().splitlines()
            if line.startswith("model name")
        ),
        "unknown",
    )
    return {
        "os": platform.system(),
        "kernel": platform.release(),
        "python": platform.python_version(),
        "cpu": cpu,
        "logical_cpus": os.cpu_count(),
        "available_memory_mib": available_memory_mib(),
        "gpu": command(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader",
            ]
        ),
        "gpu_baseline": gpu_snapshot(),
        "ollama_cli": command(["ollama", "--version"]),
    }


@asynccontextmanager
async def server(kind, config):
    """Reserve the port until the child inherits its listening socket (no free-port race)."""
    with tempfile.TemporaryDirectory(prefix="gateway-benchmark-") as temporary:
        config_path = Path(temporary) / "config.json"
        config_path.write_text(json.dumps(config))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(128)
            sock.set_inheritable(True)
            port = sock.getsockname()[1]
            with (Path(temporary) / "server.log").open("w+") as log:
                process = await asyncio.to_thread(
                    subprocess.Popen,
                    [
                        sys.executable,
                        "-m",
                        "benchmarks.server",
                        kind,
                        str(config_path),
                        str(sock.fileno()),
                    ],
                    cwd=ROOT,
                    pass_fds=(sock.fileno(),),
                    stdout=log,
                    stderr=log,
                )
                try:
                    async with httpx.AsyncClient(trust_env=False, timeout=1) as c:
                        async with asyncio.timeout(15):
                            for _ in range(300):
                                if process.poll() is not None:
                                    log.seek(0)
                                    raise RuntimeError(
                                        "Benchmark server failed: " + log.read()[-2500:]
                                    )
                                try:
                                    if (
                                        await c.get(f"http://127.0.0.1:{port}/health")
                                    ).status_code == 200:
                                        break
                                except httpx.HTTPError:
                                    pass
                                await asyncio.sleep(0.05)
                            else:
                                raise RuntimeError("Benchmark server did not become ready")
                    yield f"http://127.0.0.1:{port}", process.pid
                finally:
                    process.terminate()
                    try:
                        await asyncio.to_thread(process.wait, 5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        await asyncio.to_thread(process.wait)


class ResourceSampler:
    def __init__(self, pid, gpu=False):
        self.pid, self.gpu = pid, gpu
        self.samples = []
        self.context = {}
        self.stop = asyncio.Event()

    def process_sample(self):
        fields = Path(f"/proc/{self.pid}/stat").read_text().rsplit(")", 1)[1].split()
        ticks = int(fields[11]) + int(fields[12])
        status = Path(f"/proc/{self.pid}/status").read_text()
        rss = next(
            int(x.split()[1]) / 1024 for x in status.splitlines() if x.startswith("VmRSS:")
        )
        return ticks, rss

    async def run(self):
        previous = None
        while not self.stop.is_set():
            now = perf_counter()
            row = {
                **self.context,
                "time_s": now,
                "gateway_rss_mib": None,
                "gateway_cpu_pct": None,
                "gpu_used_mib": None,
                "gpu_total_mib": None,
                "gpu_utilization_pct": None,
            }
            try:
                ticks, rss = await asyncio.to_thread(self.process_sample)
                row["gateway_rss_mib"] = rss
                if previous:
                    row["gateway_cpu_pct"] = (
                        (ticks - previous[0])
                        / os.sysconf("SC_CLK_TCK")
                        / (now - previous[1])
                        * 100
                    )
                previous = ticks, now
            except (OSError, StopIteration):
                pass
            if self.gpu:
                sample = await asyncio.to_thread(gpu_snapshot)
                if sample:
                    row.update(
                        gpu_used_mib=sample["used_mib"],
                        gpu_total_mib=sample["total_mib"],
                        gpu_utilization_pct=sample["utilization_pct"],
                    )
            self.samples.append(row)
            try:
                await asyncio.wait_for(self.stop.wait(), 0.5)
            except TimeoutError:
                pass
