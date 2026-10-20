from time import perf_counter

from app.domain.schemas import ChatRequest, ChatResponse
from app.providers.router import ProviderRouter


class ChatService:
    def __init__(self, router: ProviderRouter) -> None:
        self.router = router

    async def generate(self, request: ChatRequest, request_id: str) -> ChatResponse:
        provider, mapping = self.router.resolve(request.model)
        started = perf_counter()
        result = await provider.generate(request, mapping.upstream_model)
        return ChatResponse(
            answer=result.answer,
            model=request.model,
            request_id=request_id,
            usage=result.usage,
            latency_ms=round((perf_counter() - started) * 1000, 3),
        )
