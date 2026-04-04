from __future__ import annotations

from pydantic import BaseModel, Field


class ExecRequest(BaseModel):
    command: str
    cwd: str = Field(default="/workspace")
    timeout: int = Field(default=60)


class ProcessRequest(BaseModel):
    command: str
    cwd: str = Field(default="/workspace")
