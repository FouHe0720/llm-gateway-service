import json
from time import perf_counter

import httpx


def native_payload(payload):
    options = {"num_ctx": 1024, "num_predict": payload.get("max_tokens", 64)}
    for field in ("temperature", "top_p", "seed"):
        if field in payload:
            options[field] = payload[field]
    return {
        "model": payload["model"],
        "messages": payload["messages"],
        "stream": True,
        "options": options,
        "keep_alive": "2m",
    }


async def request(client, url, payload, rid, *, gateway=True, native=False, streaming=False):
    start = perf_counter()
    row = {
        "request_id": rid,
        "start_s": start,
        "success": False,
        "status": None,
        "error": None,
        "answer": "",
        "first_delta_ms": None,
        "upstream_attempts": 0,
        "retries": 0,
        "fallback_count": 0,
        "cache_status": "disabled",
        "queue_ms": None,
        "load_ms": None,
        "decode_tps": None,
        "output_tokens": None,
    }
    metadata, usage = {}, None
    try:
        if native:
            body = native_payload(payload)
            body["stream"] = streaming
            endpoint = "/api/chat"
        else:
            body = dict(payload)
            endpoint = "/v1/chat/stream" if streaming else "/v1/chat"
            if not gateway:
                body.pop("task_type", None)
                body["stream"] = streaming
                endpoint = "/v1/chat/completions"
        headers = {"X-Request-ID": rid}
        if streaming:
            terminal = False
            event = None
            async with client.stream(
                "POST", url + endpoint, json=body, headers=headers
            ) as response:
                row["status"] = response.status_code
                if response.status_code != 200:
                    row["error"] = "http_" + str(response.status_code)
                else:
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        if native:
                            data = json.loads(line)
                            delta = data.get("message", {}).get("content", "")
                            if data.get("done"):
                                terminal = True
                                usage = {"completion_tokens": data.get("eval_count")}
                                metadata["timing"] = {
                                    "eval_count": data.get("eval_count"),
                                    "eval_duration_ns": data.get("eval_duration"),
                                    "load_duration_ns": data.get("load_duration"),
                                }
                        elif line.startswith("event: "):
                            event = line[7:]
                            continue
                        elif line.startswith("data: "):
                            data = json.loads(line[6:])
                            delta = data.get("delta", "")
                            if event == "done":
                                terminal = True
                                metadata, usage = data.get("metadata") or {}, data.get("usage")
                            elif event == "error":
                                row["error"] = data["error"]["code"]
                        else:
                            continue
                        if delta:
                            if row["first_delta_ms"] is None:
                                row["first_delta_ms"] = (perf_counter() - start) * 1000
                            row["answer"] += delta
            row["success"] = terminal and not row["error"]
            if not terminal and not row["error"]:
                row["error"] = "missing_terminal_event"
        else:
            response = await client.post(url + endpoint, json=body, headers=headers)
            row["status"] = response.status_code
            data = response.json()
            if response.status_code == 200:
                row["answer"] = (
                    data["answer"] if gateway else data["choices"][0]["message"]["content"]
                )
                metadata, usage = data.get("metadata") or {}, data.get("usage")
                row["success"] = isinstance(row["answer"], str)
            else:
                error = data.get("error", {})
                row["error"] = (
                    error.get("code", "http_" + str(response.status_code))
                    if isinstance(error, dict)
                    else "upstream_error"
                )
                metadata = error.get("metadata") or {} if isinstance(error, dict) else {}
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        row["error"] = type(exc).__name__
    row["end_s"] = perf_counter()
    row["latency_ms"] = (row["end_s"] - start) * 1000
    for source, target in [
        ("attempts", "upstream_attempts"),
        ("retries", "retries"),
        ("fallback_count", "fallback_count"),
        ("cache_status", "cache_status"),
        ("queue_ms", "queue_ms"),
        ("served_model", "served_model"),
    ]:
        if source in metadata:
            row[target] = metadata[source]
    if not gateway:
        row["upstream_attempts"] = 1
    timing = metadata.get("timing") or {}
    if timing.get("load_duration_ns") is not None:
        row["load_ms"] = timing["load_duration_ns"] / 1e6
    if timing.get("eval_count") is not None and timing.get("eval_duration_ns"):
        row["decode_tps"] = timing["eval_count"] * 1e9 / timing["eval_duration_ns"]
    if usage:
        row["output_tokens"] = usage.get("completion_tokens")
    return row
