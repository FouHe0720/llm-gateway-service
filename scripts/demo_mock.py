import asyncio
import socket

import uvicorn

from app.core.config import ModelMapping, Settings
from app.main import create_app
from scripts.smoke_test import smoke


async def main() -> None:
    # Explicit overrides isolate the demo from a user's real provider configuration.
    settings = Settings(
        _env_file=None,
        gateway_environment="development",
        gateway_auth_enabled=False,
        gateway_models=[ModelMapping(model="mock-echo", provider="mock")],
        gateway_rate_limit_requests=60,
        mock_chunk_delay_seconds=0.02,
    )
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.setblocking(False)
        port = sock.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(
                create_app(settings),
                log_level="warning",
                access_log=False,
            )
        )
        task = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if task.done():
                        await task
                    await asyncio.sleep(0.01)
            print(f"Offline Mock demo: http://127.0.0.1:{port}", flush=True)
            await smoke(f"http://127.0.0.1:{port}")
        finally:
            server.should_exit = True
            await asyncio.wait_for(task, 5)


if __name__ == "__main__":
    asyncio.run(main())
