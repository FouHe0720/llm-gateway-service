from fastapi import APIRouter, Depends, Request

from app.core.security import authenticate

router = APIRouter()


@router.get("/metrics", tags=["operations"], dependencies=[Depends(authenticate)])
async def metrics(request: Request) -> dict:
    return request.app.state.metrics.snapshot()
