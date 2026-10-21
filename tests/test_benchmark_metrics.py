import json
from pathlib import Path

import pytest

from benchmarks.metrics import percentile, summarize, variability
from benchmarks.workloads import grade, repeated_prompts, tasks


def test_nearest_rank_and_missing_metrics():
    assert percentile(list(range(1, 101)), 0.95) == 95
    assert percentile([None, 2, 1], 0.5) == 1
    assert percentile([], 0.95) is None


def test_success_denominator_and_goodput():
    rows = []
    for index, success in enumerate([True, False, True, False]):
        rows.append(
            dict(
                experiment="E",
                mode="real",
                scenario="test",
                strategy="gateway",
                model="m",
                concurrency=1,
                repeat=0,
                phase="warm",
                start_s=index,
                end_s=index + 1,
                latency_ms=1000,
                success=success,
                upstream_attempts=1,
                correct=success,
            )
        )
    result = next(r for r in summarize(rows) if r["phase"] == "warm")
    assert result["success_rate"] == 0.5
    assert result["accuracy"] == 0.5
    assert result["qps"] == 0.5
    assert result["decode_tps_p50"] is None
    assert variability([result])[0]["qps"]["stdev"] is None


@pytest.mark.parametrize("rate,unique", [(0, 100), (0.5, 50), (0.9, 10)])
def test_repeated_dataset_exact_count_and_seed(rate, unique):
    one = repeated_prompts(100, rate, 42)
    assert len(set(one)) == unique
    assert one == repeated_prompts(100, rate, 42)


def test_fixed_grader_and_tasks():
    assert grade("  NO\n", "no")
    assert not grade("The answer is NO", "NO")
    assert len(tasks(42)) == 18
    assert tasks(42) == tasks(42)
    raw = json.loads(Path("benchmarks/data/tasks.json").read_text())
    assert {x["task_type"] for x in raw} == {"extract", "arithmetic", "reasoning"}
