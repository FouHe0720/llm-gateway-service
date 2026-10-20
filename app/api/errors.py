from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.domain.errors import GatewayError
from app.domain.schemas import ErrorResponse

ERROR_RESPONSES = {
    status: {
        "model": ErrorResponse,
        "description": message,
        "content": {
            "application/json": {
                "example": {
                    "error": {"code": code, "message": message, "request_id": "demo-request"}
                }
            }
        },
    }
    for status, code, message in [
        (401, "unauthorized", "Valid gateway Bearer API key required"),
        (404, "model_not_found", "Requested model is not enabled"),
        (413, "request_too_large", "Request body exceeds size limit"),
        (422, "validation_error", "Request fields failed validation"),
        (429, "rate_limited", "Gateway or upstream request rate limit exceeded"),
        (500, "internal_error", "Unexpected gateway error"),
        (502, "provider_error", "Upstream provider failed"),
        (504, "provider_timeout", "Upstream provider timed out"),
    ]
}


async def gateway_error(request: Request, exc: GatewayError) -> JSONResponse:
    headers = {}
    if exc.status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    if getattr(request.state, "retry_after", None):
        headers["Retry-After"] = str(request.state.retry_after)
    return JSONResponse(
        status_code=exc.status,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request.state.request_id,
            }
        },
        headers=headers,
    )


async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Pydantic errors can contain raw prompt inputs: never echo or log them.
    return await gateway_error(
        request, GatewayError("validation_error", "Request fields failed validation", 422)
    )


async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return await gateway_error(
        request,
        GatewayError("http_error", "HTTP request could not be handled", exc.status_code),
    )
