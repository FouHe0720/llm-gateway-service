from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from app.domain.schemas import ChatRequest, Usage


@dataclass(frozen=True)
class Generation:
    answer: str
    usage: Usage | None = None


@dataclass(frozen=True)
class StreamChunk:
    delta: str = ""
    usage: Usage | None = None


class BaseLLMProvider(Protocol):
    async def generate(self, request: ChatRequest, model: str) -> Generation: ...

    def stream(self, request: ChatRequest, model: str) -> AsyncIterator[StreamChunk]: ...

    def list_models(self) -> list[str]: ...
