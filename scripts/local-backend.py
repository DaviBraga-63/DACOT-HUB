"""Run the development backend with a local shutdown marker."""

import asyncio
import os
import sys
from pathlib import Path

import dotenv
import uvicorn


async def main():
    # Keep development isolated even with older python-dotenv versions.
    dotenv.load_dotenv = lambda *args, **kwargs: False
    marker = Path(os.environ["LOCAL_STATE_DIR"]) / "backend.stop"
    server = uvicorn.Server(uvicorn.Config(
        "server:app", host="127.0.0.1", port=int(os.environ["LOCAL_HUB_PORT"]),
        timeout_graceful_shutdown=10, access_log=False,
    ))
    serve = asyncio.create_task(server.serve())
    while not serve.done() and not marker.exists():
        await asyncio.wait({serve}, timeout=0.25)
    server.should_exit = True
    await serve
    if not server.started:
        raise SystemExit(1)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    asyncio.run(main())
