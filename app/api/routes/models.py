from fastapi import APIRouter, Depends, Request

from app.core.security import guard
from app.domain.schemas import ModelList

router = APIRouter(dependencies=[Depends(guard)])


@router.get("/v1/models", response_model=ModelList, tags=["models"])
async def models(request: Request) -> ModelList:
    return ModelList(models=request.app.state.router.list_models())
