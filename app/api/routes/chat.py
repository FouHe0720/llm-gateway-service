from fastapi import APIRouter, Request

from app.domain.schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/v1/chat", response_model=ChatResponse, tags=["chat"])
async def chat(body: ChatRequest, request: Request) -> ChatResponse:
    return await request.app.state.chat.generate(body, request.state.request_id)
