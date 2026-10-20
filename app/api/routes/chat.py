from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.domain.schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/v1/chat", response_model=ChatResponse, tags=["chat"])
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    return await request.app.state.chat.generate(body, request.state.request_id)


@router.post("/v1/chat/stream", tags=["chat"], response_class=StreamingResponse)
async def stream(body: ChatRequest, request: Request) -> StreamingResponse:
    request.app.state.router.resolve(body.model)  # Unknown model remains an HTTP 404.
    return StreamingResponse(
        request.app.state.chat.stream_events(
            body, request.state.request_id, request.scope["state"]
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
