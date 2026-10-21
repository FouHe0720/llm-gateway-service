"""Build evidence tables from reviewed run IDs; no hand-entered performance values."""

import json
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "benchmarks/results"


def latest(mode):
    candidates = []
    for p in RESULTS.glob("*/manifest.json"):
        m = json.loads(p.read_text())
        if (
            m.get("mode") == mode
            and m.get("method_version") == 2
            and m.get("status") == "complete"
        ):
            if (p.parent / "summary.json").exists():
                candidates.append(p.parent)
    return sorted(candidates)[-1]


def table_row(*values):
    return "| " + " | ".join(map(str, values)) + " |"


def main():
    mock, real = latest("mock"), latest("real")
    simulated = json.loads((mock / "summary.json").read_text())
    actual = json.loads((real / "summary.json").read_text())
    pairs = json.loads((mock / "comparisons.json").read_text())
    raw = [json.loads(x) for x in (real / "requests.jsonl").read_text().splitlines()]
    assert any(x["experiment"] == "D" for x in raw) and any(x["experiment"] == "C" for x in raw)
    lines = [
        "# 实测结果（由脚本从原始数据生成）",
        "",
        f"Mock: `{mock.name}`；真实: `{real.name}`。配置、源码指纹和时间见各自 manifest。",
        "",
        "除准确率计数外，下表为逐轮指标的中位数；不把多轮任务当作新增独立题目。",
        "",
        "## A：热态、20ms 配置延迟、每组每轮 N=100、三轮",
        "",
        "| 并发 | Direct P95 ms | Gateway P95 ms | 配对 ΔP95 ms | Direct QPS | Gateway QPS |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for c in [1, 5, 20, 50]:

        def select(strategy, key, c=c):
            return median(
                r[key]
                for r in simulated
                if r["experiment"] == "A"
                and r["phase"] == "warm"
                and r["concurrency"] == c
                and r["strategy"] == strategy
            )

        delta = median(
            r["extra_p95_ms"] for r in pairs if r["phase"] == "warm" and r["concurrency"] == c
        )
        lines.append(
            table_row(
                c,
                f"{select('direct', 'p95_ms'):.2f}",
                f"{select('gateway', 'p95_ms'):.2f}",
                f"{delta:.2f}",
                f"{select('direct', 'qps'):.2f}",
                f"{select('gateway', 'qps'):.2f}",
            )
        )
    lines += [
        "",
        "## D：固定 18 题、两轮、整体含冷启动",
        "",
        "| 策略 | 正确/总请求 | 严格匹配率 | 正确任务平均耗时 ms | 每轮加载耗时合计中位数 ms |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for strategy in ["all_0.5b", "all_1.5b", "task_route"]:
        rows = [r for r in raw if r["experiment"] == "D" and r["strategy"] == strategy]
        correct = [r for r in rows if r.get("correct")]
        loads = [
            r["load_sum_ms"]
            for r in actual
            if r["experiment"] == "D" and r["strategy"] == strategy and r["phase"] == "all"
        ]
        conditional = f"{mean(r['latency_ms'] for r in correct):.2f}" if correct else "未测试"
        lines.append(
            table_row(
                strategy,
                f"{len(correct)}/{len(rows)}",
                f"{len(correct) / len(rows):.1%}",
                conditional,
                f"{median(loads):.2f}",
            )
        )
    lines += [
        "",
        "准确率同时约束答案与格式；例如 `NO.` 与 `NO` 不匹配。",
        "",
        "## E：热态 SSE、每路径每轮 N=4、两轮",
        "",
        "| 模型 | 路径 | 客户端并发 | TTFT P95 ms | E2E P95 ms | 生成 tokens/s P50 | 成功率 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in ["qwen2.5:0.5b", "qwen2.5:1.5b"]:
        for c in [1, 2]:
            for strategy in ["direct", "gateway"]:
                rows = [
                    r
                    for r in actual
                    if r["experiment"] == "E"
                    and r["model"] == model
                    and r["concurrency"] == c
                    and r["strategy"] == strategy
                    and r["phase"] == "warm"
                ]
                fields = [
                    median(r[k] for r in rows)
                    for k in ["first_delta_p95_ms", "p95_ms", "decode_tps_p50", "success_rate"]
                ]
                lines.append(
                    table_row(
                        model,
                        strategy,
                        c,
                        f"{fields[0]:.2f}",
                        f"{fields[1]:.2f}",
                        f"{fields[2]:.2f}",
                        f"{fields[3]:.1%}",
                    )
                )
    lines += [
        "",
        "## C：真实 0.5B 缓存、每组 10 条、两轮、整体含冷启动",
        "",
        "| 重复率 | 策略 | 每轮模型调用数 | 命中率 | 调用节省 | P50 ms | P95 ms |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for rate in ["repeat_0%", "repeat_50%", "repeat_90%"]:
        for strategy in ["cache_off", "cache_on"]:
            rows = [
                r
                for r in actual
                if r["experiment"] == "C"
                and r["scenario"] == rate
                and r["strategy"] == strategy
                and r["phase"] == "all"
            ]
            values = [
                median(r[k] for r in rows)
                for k in [
                    "attempts",
                    "cache_hit_rate",
                    "inference_saved_ratio",
                    "p50_ms",
                    "p95_ms",
                ]
            ]
            lines.append(
                table_row(
                    rate,
                    strategy,
                    f"{values[0]:.0f}",
                    f"{values[1]:.0%}",
                    f"{values[2]:.0%}",
                    f"{values[3]:.2f}",
                    f"{values[4]:.2f}",
                )
            )
    lines += [
        "",
        f"完整冷热表与 B 结果见 `{mock.name}/summary.csv`。",
        f"真实模型完整结果见 `{real.name}/summary.csv` 和 HTML。",
        "高并发与小批量结果仅描述当前 WSL 笔记本；没有推断生产 QPS 或统计显著性。",
    ]
    (ROOT / "docs/BENCHMARK_RESULTS.md").write_text("\n".join(lines) + "\n")
    # Explicit reviewed exceptions; development/diagnostic runs remain local without deletion.
    p = ROOT / ".gitignore"
    text = p.read_text()
    for run in [mock.name, real.name]:
        rule = "!benchmarks/results/" + run + "/"
        if rule not in text:
            text += rule + "\n"
    p.write_text(text)
    print("Generated evidence tables for", mock.name, real.name)


if __name__ == "__main__":
    main()
