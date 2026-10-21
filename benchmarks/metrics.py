import math
from collections import defaultdict
from statistics import mean, median, stdev


def percentile(values, fraction):
    clean = sorted(x for x in values if x is not None)
    return clean[max(0, math.ceil(len(clean) * fraction) - 1)] if clean else None


def summarize(rows):
    groups = defaultdict(list)
    columns = ("experiment", "mode", "scenario", "strategy", "model", "concurrency", "repeat")
    for row in rows:
        key = tuple(row.get(c) for c in columns)
        groups[(*key, row["phase"])].append(row)
        groups[(*key, "all")].append(row)
    summaries = []
    for key, data in groups.items():
        good = [r for r in data if r["success"]]
        span = max(r["end_s"] for r in data) - min(r["start_s"] for r in data)
        timings = [r["latency_ms"] for r in data]
        grades = [r for r in data if r.get("correct") is not None]
        successes = [r["latency_ms"] for r in grades if r["correct"]]
        attempted = sum(r.get("upstream_attempts") or 0 for r in data)
        summary = dict(zip((*columns, "phase"), key, strict=True))
        summary.update(
            n=len(data),
            successes=len(good),
            success_rate=len(good) / len(data),
            p50_ms=percentile(timings, 0.5),
            p95_ms=percentile(timings, 0.95),
            success_p95_ms=percentile([r["latency_ms"] for r in good], 0.95),
            qps=len(good) / span if span else None,
            attempts=attempted,
            amplification=attempted / len(data),
            retries=sum(r.get("retries") or 0 for r in data),
            fallbacks=sum(r.get("fallback_count") or 0 for r in data),
            cache_hit_rate=sum(r.get("cache_status") == "hit" for r in data) / len(data),
            inference_saved_ratio=1 - attempted / len(data)
            if data[0]["experiment"] == "C"
            else None,
            accuracy=sum(bool(r["correct"]) for r in grades) / len(grades) if grades else None,
            success_task_mean_ms=mean(successes) if successes else None,
            first_delta_p50_ms=percentile([r.get("first_delta_ms") for r in good], 0.5),
            first_delta_p95_ms=percentile([r.get("first_delta_ms") for r in good], 0.95),
            decode_tps_p50=percentile([r.get("decode_tps") for r in good], 0.5),
            load_ms_p50=percentile([r.get("load_ms") for r in good], 0.5),
            load_sum_ms=sum(r.get("load_ms") or 0 for r in data),
            output_token_goodput=sum(r.get("output_tokens") or 0 for r in good) / span
            if any(r.get("output_tokens") is not None for r in good) and span
            else None,
            queue_p95_ms=percentile([r.get("queue_ms") for r in data], 0.95),
        )
        summaries.append(summary)
    return summaries


def variability(summaries):
    grouped = defaultdict(list)
    keys = ("experiment", "mode", "scenario", "strategy", "model", "concurrency", "phase")
    for row in summaries:
        grouped[tuple(row[k] for k in keys)].append(row)
    output = []
    for key, values in grouped.items():
        entry = dict(zip(keys, key, strict=True))
        entry["repeats"] = len(values)
        for field in (
            "success_rate",
            "p95_ms",
            "qps",
            "accuracy",
            "cache_hit_rate",
            "decode_tps_p50",
        ):
            numbers = [x[field] for x in values if x[field] is not None]
            entry[field] = (
                {
                    "median": median(numbers),
                    "min": min(numbers),
                    "max": max(numbers),
                    "stdev": stdev(numbers) if len(numbers) > 1 else None,
                }
                if numbers
                else None
            )
        output.append(entry)
    return output


def comparisons(summaries):
    output = []
    for gateway in summaries:
        if gateway["experiment"] not in {"A", "E"} or gateway["strategy"] != "gateway":
            continue
        direct = next(
            (
                r
                for r in summaries
                if r["strategy"] == "direct"
                and all(
                    r[k] == gateway[k]
                    for k in (
                        "experiment",
                        "mode",
                        "scenario",
                        "phase",
                        "model",
                        "concurrency",
                        "repeat",
                    )
                )
            ),
            None,
        )
        if direct:
            output.append(
                {
                    k: gateway[k]
                    for k in (
                        "experiment",
                        "mode",
                        "scenario",
                        "phase",
                        "model",
                        "concurrency",
                        "repeat",
                    )
                }
                | {
                    "direct_n": direct["n"],
                    "gateway_n": gateway["n"],
                    "direct_p95_ms": direct["p95_ms"],
                    "gateway_p95_ms": gateway["p95_ms"],
                    "extra_p50_ms": gateway["p50_ms"] - direct["p50_ms"],
                    "extra_p95_ms": gateway["p95_ms"] - direct["p95_ms"],
                    "qps_ratio": gateway["qps"] / direct["qps"] if direct["qps"] else None,
                    "note": "Difference of matched-group percentiles",
                }
            )
    return output
