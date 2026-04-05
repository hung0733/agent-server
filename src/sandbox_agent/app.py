from __future__ import annotations

import asyncio
import logging
import re
import time
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request

from sandbox_agent.file_ops import FileOps
from sandbox_agent.models import ExecRequest, ProcessRequest
from sandbox_agent.models import (
    ApplyPatchRequest,
    EditFileRequest,
    FindFilesRequest,
    GrepFilesRequest,
    ListDirRequest,
    ReadFileRequest,
    WriteFileRequest,
)
from sandbox_agent.process_manager import ProcessManager


logger = logging.getLogger(__name__)


def create_app(api_token: str, workspace_root: str = "/workspace") -> FastAPI:
    app = FastAPI()
    manager = ProcessManager()
    file_ops = FileOps(workspace_root=workspace_root)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        request_id = request.headers.get("X-Sandbox-Request-Id", uuid4().hex)
        sandbox_id = request.headers.get("X-Sandbox-Id", "")
        request.state.request_id = request_id
        request.state.sandbox_id = sandbox_id
        started = time.perf_counter()
        logger.info(
            "sandbox.request.start request_id=%s sandbox_id=%s method=%s path=%s",
            request_id,
            sandbox_id,
            request.method,
            request.url.path,
        )
        response = await call_next(request)
        logger.info(
            "sandbox.request.end request_id=%s sandbox_id=%s method=%s path=%s status=%s duration_ms=%.2f",
            request_id,
            sandbox_id,
            request.method,
            request.url.path,
            response.status_code,
            (time.perf_counter() - started) * 1000,
        )
        return response

    def _require_token(request: Request) -> None:
        if request.headers.get("X-Sandbox-Token", "") != api_token:
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/v1/metadata")
    async def metadata(dep: None = Depends(_require_token)) -> dict:
        return {"capabilities": ["exec", "process", "files"], "workspace_root": "/workspace"}

    @app.post("/v1/exec")
    async def exec_command(request: ExecRequest, http_request: Request, dep: None = Depends(_require_token)) -> dict:
        try:
            logger.info(
                "sandbox.exec request_id=%s sandbox_id=%s cwd=%s timeout=%s",
                getattr(http_request.state, "request_id", ""),
                getattr(http_request.state, "sandbox_id", ""),
                request.cwd,
                request.timeout,
            )
            return await manager.exec(request.command, request.cwd, request.timeout)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=408, detail="timeout") from exc

    @app.post("/v1/processes")
    async def start_process(request: ProcessRequest, http_request: Request, dep: None = Depends(_require_token)) -> dict:
        try:
            logger.info(
                "sandbox.process.start request_id=%s sandbox_id=%s cwd=%s",
                getattr(http_request.state, "request_id", ""),
                getattr(http_request.state, "sandbox_id", ""),
                request.cwd,
            )
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

    @app.post("/v1/files/read")
    async def read_file(request: ReadFileRequest, dep: None = Depends(_require_token)) -> dict:
        try:
            return await file_ops.read_file(request.path, request.encoding)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/files/write")
    async def write_file(request: WriteFileRequest, http_request: Request, dep: None = Depends(_require_token)) -> dict:
        try:
            logger.info(
                "sandbox.file.write request_id=%s sandbox_id=%s path=%s bytes=%s",
                getattr(http_request.state, "request_id", ""),
                getattr(http_request.state, "sandbox_id", ""),
                request.path,
                len(request.content.encode(request.encoding)),
            )
            return await file_ops.write_file(request.path, request.content, request.encoding)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/files/edit")
    async def edit_file(request: EditFileRequest, dep: None = Depends(_require_token)) -> dict:
        try:
            return await file_ops.edit_file(request.path, request.old_string, request.new_string, request.replace_all, request.encoding)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/files/apply-patch")
    async def apply_patch(request: ApplyPatchRequest, dep: None = Depends(_require_token)) -> dict:
        try:
            return await file_ops.apply_patch(request.patch, request.strip)
        except RuntimeError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/files/grep")
    async def grep_files(request: GrepFilesRequest, dep: None = Depends(_require_token)) -> dict:
        try:
            return await file_ops.grep_files(request.pattern, request.path, request.recursive, request.ignore_case, request.include, request.max_results)
        except re.error as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/files/find")
    async def find_files(request: FindFilesRequest, dep: None = Depends(_require_token)) -> dict:
        try:
            return await file_ops.find_files(request.pattern, request.path, request.max_results)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/files/list")
    async def list_dir(request: ListDirRequest, dep: None = Depends(_require_token)) -> dict:
        try:
            return await file_ops.list_dir(request.path, request.show_hidden)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return app
