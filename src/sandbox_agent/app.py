from __future__ import annotations

import asyncio

from fastapi import Depends, FastAPI, HTTPException, Request

from sandbox_agent.models import ExecRequest, ProcessRequest
from sandbox_agent.process_manager import ProcessManager


def create_app(api_token: str) -> FastAPI:
    app = FastAPI()
    manager = ProcessManager()

    def _require_token(request: Request) -> None:
        if request.headers.get("X-Sandbox-Token", "") != api_token:
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/metadata")
    async def metadata(dep: None = Depends(_require_token)) -> dict:
        return {"capabilities": ["exec", "process"], "workspace_root": "/workspace"}

    @app.post("/v1/exec")
    async def exec_command(request: ExecRequest, dep: None = Depends(_require_token)) -> dict:
        try:
            return await manager.exec(request.command, request.cwd, request.timeout)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=408, detail="timeout") from exc

    @app.post("/v1/processes")
    async def start_process(request: ProcessRequest, dep: None = Depends(_require_token)) -> dict:
        try:
            return await manager.start_process(request.command, request.cwd)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/processes/{handle}")
    async def get_process(handle: str, dep: None = Depends(_require_token)) -> dict:
        try:
            return await manager.get_process(handle)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc

    @app.delete("/v1/processes/{handle}")
    async def kill_process(handle: str, dep: None = Depends(_require_token)) -> dict:
        try:
            return await manager.kill_process(handle)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc

    return app
