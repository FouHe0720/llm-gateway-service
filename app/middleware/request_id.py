import asyncio
import logging
import re
from time import perf_counter
from uuid import uuid4

from starlette.requests import ClientDisconnect
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.infra.metrics import Metrics, route_label

logger = logging.getLogger("gateway")
SAFE_ID = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


class RequestContextMiddleware:
    """Pure ASGI: preserve StreamingResponse's disconnect and cancellation semantics."""

    def __init__(self, app: ASGIApp, metrics: Metrics, max_body_bytes: int) -> None:
        self.app, self.metrics, self.max_body_bytes = app, metrics, max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        candidate = headers.get(b"x-request-id", b"").decode("latin-1")
        request_id = candidate if SAFE_ID.fullmatch(candidate) else uuid4().hex
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        started, status, sent = perf_counter(), 500, False
        route = route_label(scope["path"])
        self.metrics.active += 1

        async def send_with_id(message: Message) -> None:
            nonlocal status, sent
            if message["type"] == "http.response.start":
                status, sent = message["status"], True
                response_headers = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() != b"x-request-id"
                ]
                message["headers"] = response_headers + [(b"x-request-id", request_id.encode())]
            await send(message)

        async def error(code: str, message: str, status_code: int) -> None:
            response = JSONResponse(
                {"error": {"code": code, "message": message, "request_id": request_id}},
                status_code=status_code,
            )
            await response(scope, receive, send_with_id)

        try:
            buffered = bytearray()
            if scope["method"] in {"POST", "PUT", "PATCH"}:
                length = headers.get(b"content-length")
                if length and (not length.isdigit() or int(length) > self.max_body_bytes):
                    await error("request_too_large", "Request body exceeds size limit", 413)
                    return
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        state["cancelled"] = True
                        return
                    buffered.extend(message.get("body", b""))
                    if len(buffered) > self.max_body_bytes:
                        await error("request_too_large", "Request body exceeds size limit", 413)
                        return
                    if not message.get("more_body", False):
                        break
                consumed = False

                async def replay_body() -> Message:
                    nonlocal consumed
                    if not consumed:
                        consumed = True
                        return {
                            "type": "http.request",
                            "body": bytes(buffered),
                            "more_body": False,
                        }
                    return await receive()

                await self.app(scope, replay_body, send_with_id)
            else:
                await self.app(scope, receive, send_with_id)
        except (asyncio.CancelledError, ClientDisconnect):
            state["cancelled"] = True
            raise
        except Exception:
            state["stream_error"] = "internal_error"
            if not sent:
                await error("internal_error", "Unexpected gateway error", 500)
            else:
                raise
        finally:
            duration = (perf_counter() - started) * 1000
            self.metrics.active -= 1
            self.metrics.record(route, status, duration, state)
            logger.info(
                "request_complete",
                extra={
                    "fields": {
                        "request_id": request_id,
                        "route": route,
                        "status": status,
                        "latency_ms": round(duration, 3),
                        "stream_error": state.get("stream_error"),
                        "cancelled": bool(state.get("cancelled")),
                    }
                },
            )
