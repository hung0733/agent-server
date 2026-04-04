from __future__ import annotations

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field


class ProvisionerSandbox(BaseModel):
    sandbox_id: str
    owner_id: str
    scope: str
    scope_key: str
    profile: str
    network_mode: str
    mounts: list[dict] = Field(default_factory=list)
    endpoint: str = "http://sandbox.local"
    backend_type: str = "remote_provisioner"
    workspace_host_path: str = "/remote/workspaces"
    workspace_container_path: str = "/workspace"
    metadata: dict[str, str] = Field(default_factory=lambda: {"sandbox_token": "local-token"})


def build_provisioner_app(api_token: str = "") -> FastAPI:
    app = FastAPI()
    sandboxes: dict[str, ProvisionerSandbox] = {}

    def _require_token(x_provisioner_token: str = Header(default="")) -> None:
        if api_token and x_provisioner_token != api_token:
            raise HTTPException(status_code=401, detail="unauthorized")

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/sandboxes")
    async def create_sandbox(request: ProvisionerSandbox, dep: None = Depends(_require_token)) -> dict:
        existing = sandboxes.get(request.sandbox_id)
        if existing is not None:
            return existing.model_dump()
        sandboxes[request.sandbox_id] = request
        return request.model_dump()

    @app.get("/api/sandboxes/{sandbox_id}")
    async def get_sandbox(sandbox_id: str, dep: None = Depends(_require_token)) -> dict:
        sandbox = sandboxes.get(sandbox_id)
        if sandbox is None:
            raise HTTPException(status_code=404, detail="not found")
        return sandbox.model_dump()

    @app.delete("/api/sandboxes/{sandbox_id}")
    async def delete_sandbox(sandbox_id: str, dep: None = Depends(_require_token)) -> dict:
        sandbox = sandboxes.pop(sandbox_id, None)
        if sandbox is None:
            raise HTTPException(status_code=404, detail="not found")
        return {"deleted": sandbox_id}

    return app
