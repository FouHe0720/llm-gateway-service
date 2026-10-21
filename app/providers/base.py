from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol

from app.domain.schemas import ChatRequest, ProviderTiming, Usage


@dataclass(frozen=True)
class Generation:
    answer: str
    usage: Usage | None = None
    timing: ProviderTiming | None = None


@dataclass(frozen=True)
class StreamChunk:
    delta: str = ""
    usage: Usage | None = None
    timing: ProviderTiming | None = None


class BaseLLMProvider(Protocol):
    async def generate(self, request: ChatRequest, model: str) -> Generation: ...

    def stream(self, request: ChatRequest, model: str) -> AsyncGenerator[StreamChunk, None]: ...

    def list_models(self) -> list[str]: ...
