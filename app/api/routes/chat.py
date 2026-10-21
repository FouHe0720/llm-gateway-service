from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from app.core.security import guard
from app.domain.schemas import ChatRequest, ChatResponse

router = APIRouter(dependencies=[Depends(guard)])


@router.post(
    "/v1/chat",
    response_model=ChatResponse,
    tags=["chat"],
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "answer": "[mock] Hello Gateway",
                        "model": "mock-echo",
                        "request_id": "demo-request",
                        "usage": None,
                        "latency_ms": 0.1,
                    }
                }
            }
        }
    },
)
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    return await request.app.state.chat.generate(body, request.state.request_id)


@router.post(
    "/v1/chat/stream",
    tags=["chat"],
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "example": 'event: start\ndata: {"request_id":"demo-request",'
                    '"model":"mock-echo",'
                    '"simulated":true}\n\nevent: delta\ndata: {"request_id":"demo-request",'
                    '"model":"mock-echo","delta":"hello"}\n\n'
                }
            }
        }
    },
)
async def stream(body: ChatRequest, request: Request) -> StreamingResponse:
    alias = request.app.state.router.route(body.model, body.task_type)
    request.app.state.router.resolve(alias)  # Unknown model remains an HTTP 404.
    return StreamingResponse(
        request.app.state.chat.stream_events(
            body, request.state.request_id, request.scope["state"]
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
