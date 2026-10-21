from contextvars import ContextVar
from dataclasses import dataclass

from app.domain.errors import ProviderError


@dataclass
class RequestTrace:
    max_attempts: int
    request_id: str = ""
    attempts: int = 0
    retries: int = 0


current_trace: ContextVar[RequestTrace | None] = ContextVar("request_trace", default=None)


def trace_headers() -> dict[str, str]:
    trace = current_trace.get()
    return {"X-Request-ID": trace.request_id} if trace and trace.request_id else {}


def record_attempt(retry: bool = False) -> None:
    trace = current_trace.get()
    if trace is not None:
        if trace.attempts >= trace.max_attempts:
            raise ProviderError("Request upstream attempt budget exhausted")
        trace.attempts += 1
        trace.retries += int(retry)
