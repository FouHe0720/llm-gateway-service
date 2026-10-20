import math
from collections import deque
from time import monotonic


class SlidingWindowLimiter:
    """One bounded, process-wide window; no IP/key-derived unbounded dictionaries."""

    def __init__(self, limit: int, window: float) -> None:
        self.limit = limit
        self.window = window
        self.timestamps: deque[float] = deque()

    def consume(self) -> int | None:
        now = monotonic()
        while self.timestamps and self.timestamps[0] <= now - self.window:
            self.timestamps.popleft()
        if len(self.timestamps) >= self.limit:
            return max(1, math.ceil(self.timestamps[0] + self.window - now))
        self.timestamps.append(now)
        return None
