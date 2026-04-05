from __future__ import annotations

from pydantic import BaseModel, Field


class ExecRequest(BaseModel):
    command: str
    cwd: str = Field(default="/workspace")
    timeout: int = Field(default=60)


class ProcessRequest(BaseModel):
    command: str
    cwd: str = Field(default="/workspace")


class ReadFileRequest(BaseModel):
    path: str
    encoding: str = Field(default="utf-8")


class WriteFileRequest(BaseModel):
    path: str
    content: str
    encoding: str = Field(default="utf-8")


class EditFileRequest(BaseModel):
    path: str
    old_string: str
    new_string: str
    replace_all: bool = Field(default=False)
    encoding: str = Field(default="utf-8")


class ApplyPatchRequest(BaseModel):
    patch: str
    strip: int = Field(default=1)


class GrepFilesRequest(BaseModel):
    pattern: str
    path: str = Field(default=".")
    recursive: bool = Field(default=True)
    ignore_case: bool = Field(default=False)
    include: str = Field(default="")
    max_results: int = Field(default=100)


class FindFilesRequest(BaseModel):
    pattern: str
    path: str = Field(default=".")
    max_results: int = Field(default=200)


class ListDirRequest(BaseModel):
    path: str = Field(default=".")
    show_hidden: bool = Field(default=False)
