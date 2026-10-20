import asyncio
from collections.abc import AsyncIterator

from app.domain.schemas import ChatRequest
from app.providers.base import Generation, StreamChunk


class MockProvider:
    """Deterministic echo, simulated chunks, no token accounting claims."""

    def __init__(self, models: list[str], delay: float = 0.02) -> None:
        self.models = models
        self.delay = delay

    def list_models(self) -> list[str]:
        return self.models.copy()

    @staticmethod
    def answer(request: ChatRequest) -> str:
        return "[mock] " + request.messages[-1].content

    async def generate(self, request: ChatRequest, model: str) -> Generation:
        return Generation(answer=self.answer(request))

    async def stream(self, request: ChatRequest, model: str) -> AsyncIterator[StreamChunk]:
        answer = self.answer(request)
        for offset in range(0, len(answer), 4):
            await asyncio.sleep(self.delay)
            yield StreamChunk(delta=answer[offset : offset + 4])
