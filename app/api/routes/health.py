from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
