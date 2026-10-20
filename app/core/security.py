from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.domain.errors import GatewayError

bearer = HTTPBearer(auto_error=False)


async def authenticate(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    settings = request.app.state.settings
    if not settings.gateway_auth_enabled:
        return
    candidate = credentials.credentials if credentials else ""
    expected = settings.gateway_api_key.get_secret_value()
    if not compare_digest(candidate.encode("utf-8"), expected.encode("utf-8")):
        raise GatewayError("unauthorized", "Valid gateway Bearer API key required", 401)


async def guard(request: Request, _: Annotated[None, Depends(authenticate)]) -> None:
    retry_after = request.app.state.limiter.consume()
    if retry_after is not None:
        request.state.retry_after = retry_after
        raise GatewayError("rate_limited", "Gateway request rate limit exceeded", 429)
