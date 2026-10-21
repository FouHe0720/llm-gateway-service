"""Behavioral oracles; performance numbers are never pass/fail targets."""

from collections import defaultdict


def verify_mock(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[(r["experiment"], r["scenario"], r["strategy"], r["repeat"])].append(r)
        assert r["upstream_attempts"] <= 6, "Attempt budget exceeded"
    for (experiment, scenario, strategy, _), data in groups.items():
        if experiment in {"A", "C", "D", "E"}:
            assert all(r["success"] for r in data), f"{experiment}: unexpected failure"
        if experiment == "B":
            warm = [r for r in data if r["phase"] == "warm"]
            if strategy == "retry_fallback" or (
                scenario in {"503", "429"} and strategy == "retry"
            ):
                assert all(r["success"] for r in warm), "Recovery did not complete"
            elif scenario == "connect":
                assert not any(r["success"] for r in warm), "Expected refused connection"
            else:
                failures = sum(not r["success"] for r in warm)
                assert failures == len(warm[::5]), f"Wrong injected failures: {failures}"
        if experiment == "C":
            repeat_rate = int(scenario.removeprefix("repeat_").removesuffix("%")) / 100
            expected_calls = (
                max(1, round(len(data) * (1 - repeat_rate)))
                if strategy == "cache_on"
                else len(data)
            )
            assert sum(r["upstream_attempts"] for r in data) == expected_calls, (
                "Cache call accounting mismatch"
            )
        if experiment == "D":
            assert all(r.get("correct") is None for r in data), (
                "Mock must not claim LLM accuracy"
            )
        if experiment == "E":
            assert all(r["decode_tps"] is None for r in data), (
                "Mock must not invent token speed"
            )
    return {"status": "passed", "records_checked": len(rows)}
