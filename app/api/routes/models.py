from fastapi import APIRouter, Request

from app.domain.schemas import ModelList

router = APIRouter()


@router.get("/v1/models", response_model=ModelList, tags=["models"])
async def models(request: Request) -> ModelList:
    return ModelList(models=request.app.state.router.list_models())
