from collections import Counter

ROUTES = {
    "/v1/chat",
    "/v1/chat/stream",
    "/v1/models",
    "/health",
    "/metrics",
    "/docs",
    "/openapi.json",
}
BUCKETS_MS = (10, 50, 100, 250, 500, 1000, 5000, 20_000, 60_000)


def route_label(path: str) -> str:
    return path if path in ROUTES else "other"


class Metrics:
    def __init__(self) -> None:
        self.requests: Counter[str] = Counter()
        self.failures: Counter[str] = Counter()
        self.cancelled: Counter[str] = Counter()
        self.buckets: Counter[int] = Counter()
        self.duration_sum_ms = 0.0
        self.active = 0

    def record(self, route: str, status: int, duration_ms: float, state: dict) -> None:
        self.requests[route] += 1
        if status >= 400 or state.get("stream_error"):
            self.failures[route] += 1
        if state.get("cancelled"):
            self.cancelled[route] += 1
        self.duration_sum_ms += duration_ms
        for bound in BUCKETS_MS:
            if duration_ms <= bound:
                self.buckets[bound] += 1

    def snapshot(self) -> dict:
        return {
            "scope": "single_process",
            "requests_total": dict(self.requests),
            "failures_total": dict(self.failures),
            "cancelled_total": dict(self.cancelled),
            "active_requests": self.active,
            "latency_ms": {
                "count": sum(self.requests.values()),
                "sum": round(self.duration_sum_ms, 3),
                "cumulative_buckets": {
                    **{str(bound): self.buckets[bound] for bound in BUCKETS_MS},
                    "+Inf": sum(self.requests.values()),
                },
            },
        }
