import hashlib
import json
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic

from app.domain.schemas import ChatRequest
from app.providers.base import Generation


@dataclass(frozen=True)
class CacheEntry:
    value: Generation
    expires: float
    size: int


def cache_key(request: ChatRequest, namespace: str) -> str:
    payload = json.dumps(
        {"request": request.model_dump(), "namespace": namespace},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class ResponseCache:
    """Process-local TTL/LRU bounded by count and answer bytes. No single-flight."""

    def __init__(self, ttl: float, max_entries: int, max_bytes: int) -> None:
        self.ttl, self.max_entries, self.max_bytes = ttl, max_entries, max_bytes
        self.entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self.size = 0

    def _remove(self, key: str) -> None:
        self.size -= self.entries.pop(key).size

    def get(self, key: str) -> Generation | None:
        entry = self.entries.get(key)
        if entry is None:
            return None
        if entry.expires <= monotonic():
            self._remove(key)
            return None
        self.entries.move_to_end(key)
        return Generation(entry.value.answer)  # Cached usage/timing is not a new inference.

    def put(self, key: str, value: Generation) -> None:
        now = monotonic()
        for old_key in list(self.entries):
            if self.entries[old_key].expires <= now:
                self._remove(old_key)
        size = len(value.answer.encode()) + len(key)
        if size > self.max_bytes:
            return
        if key in self.entries:
            self._remove(key)
        while self.entries and (
            len(self.entries) >= self.max_entries or self.size + size > self.max_bytes
        ):
            self._remove(next(iter(self.entries)))
        self.entries[key] = CacheEntry(Generation(value.answer), now + self.ttl, size)
        self.size += size
