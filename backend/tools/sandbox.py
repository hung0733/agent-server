import logging
from typing import Any

from langchain.tools import tool, ToolRuntime
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from backend.i18n import t
from backend.sandbox.agent_sandbox import AgentSandbox

logger = logging.getLogger(__name__)


class RunCommandArgs(BaseModel):
    command: str = Field(description=t("tools.sandbox.run_command.command.description"))


class WriteFileArgs(BaseModel):
    path: str = Field(description=t("tools.sandbox.path.description"))
    content: str = Field(description=t("tools.sandbox.write_file.content.description"))


class ReadFileArgs(BaseModel):
    path: str = Field(description=t("tools.sandbox.path.description"))


class ListFilesArgs(BaseModel):
    path: str = Field(default=".", description=t("tools.sandbox.path.description"))
    pattern: str = Field(
        default="*",
        description=t("tools.sandbox.list_files.pattern.description"),
    )


class DeleteFileArgs(BaseModel):
    path: str = Field(description=t("tools.sandbox.path.description"))


class CopyArgs(BaseModel):
    src: str = Field(description=t("tools.sandbox.src.description"))
    dest: str = Field(description=t("tools.sandbox.dest.description"))


class RenameArgs(BaseModel):
    src: str = Field(description=t("tools.sandbox.src.description"))
    dest: str = Field(description=t("tools.sandbox.dest.description"))


class PwdArgs(BaseModel):
    pass


class CdArgs(BaseModel):
    path: str = Field(description=t("tools.sandbox.cd.path.description"))


@tool(
    args_schema=RunCommandArgs,
    description=t("tools.sandbox.run_command.description"),
)
async def run_command(command: str, runtime: ToolRuntime) -> Any:
    """Run a shell command in the configured agent sandbox."""
    sandbox = _sandbox_from_runtime(runtime)
    _log_run_command_started(sandbox.sandbox_id, command)
    try:
        ret: dict[str, Any] = await sandbox.run_command(command)
    except Exception:
        _log_run_command_failed(sandbox.sandbox_id, command)
        raise

    result = ret["result"]
    _log_run_command_completed(sandbox.sandbox_id, result)
    return ret["result"]


@tool(
    args_schema=WriteFileArgs,
    description=t("tools.sandbox.write_file.description"),
)
async def write_file(path: str, content: str, runtime: ToolRuntime) -> Any:
    """Write text content to a file in the configured agent sandbox."""
    sandbox = _sandbox_from_runtime(runtime)
    _log_started("write_file", sandbox.sandbox_id)
    try:
        ret = await sandbox.write_file(path, content)
    except Exception:
        _log_failed("write_file", sandbox.sandbox_id)
        raise
    _log_completed("write_file", sandbox.sandbox_id)
    return ret


@tool(
    args_schema=ReadFileArgs,
    description=t("tools.sandbox.read_file.description"),
)
async def read_file(path: str, runtime: ToolRuntime) -> Any:
    """Read a text file from the configured agent sandbox."""
    sandbox = _sandbox_from_runtime(runtime)
    _log_started("read_file", sandbox.sandbox_id)
    try:
        ret = await sandbox.read_file(path)
    except Exception:
        _log_failed("read_file", sandbox.sandbox_id)
        raise
    _log_completed("read_file", sandbox.sandbox_id)
    return ret


@tool(
    args_schema=ListFilesArgs,
    description=t("tools.sandbox.list_files.description"),
)
async def list_files(
    runtime: ToolRuntime,
    path: str = ".",
    pattern: str = "*",
) -> Any:
    """List files in the configured agent sandbox."""
    sandbox = _sandbox_from_runtime(runtime)
    _log_started("list_files", sandbox.sandbox_id)
    try:
        ret = await sandbox.list_files(path, pattern)
    except Exception:
        _log_failed("list_files", sandbox.sandbox_id)
        raise
    _log_completed("list_files", sandbox.sandbox_id)
    return ret


@tool(
    args_schema=DeleteFileArgs,
    description=t("tools.sandbox.delete_file.description"),
)
async def delete_file(path: str, runtime: ToolRuntime) -> Any:
    """Delete a file in the configured agent sandbox."""
    sandbox = _sandbox_from_runtime(runtime)
    _log_started("delete_file", sandbox.sandbox_id)
    try:
        ret = await sandbox.delete_file(path)
    except Exception:
        _log_failed("delete_file", sandbox.sandbox_id)
        raise
    _log_completed("delete_file", sandbox.sandbox_id)
    return ret


@tool(
    args_schema=CopyArgs,
    description=t("tools.sandbox.copy.description"),
)
async def copy(src: str, dest: str, runtime: ToolRuntime) -> Any:
    """Copy a file or directory in the configured agent sandbox."""
    sandbox = _sandbox_from_runtime(runtime)
    _log_started("copy", sandbox.sandbox_id)
    try:
        ret = await sandbox.copy(src, dest)
    except Exception:
        _log_failed("copy", sandbox.sandbox_id)
        raise
    _log_completed("copy", sandbox.sandbox_id)
    return ret


@tool(
    args_schema=RenameArgs,
    description=t("tools.sandbox.rename.description"),
)
async def rename(src: str, dest: str, runtime: ToolRuntime) -> Any:
    """Rename or move a file or directory in the configured agent sandbox."""
    sandbox = _sandbox_from_runtime(runtime)
    _log_started("rename", sandbox.sandbox_id)
    try:
        ret = await sandbox.rename(src, dest)
    except Exception:
        _log_failed("rename", sandbox.sandbox_id)
        raise
    _log_completed("rename", sandbox.sandbox_id)
    return ret


@tool(
    args_schema=PwdArgs,
    description=t("tools.sandbox.pwd.description"),
)
async def pwd(config: RunnableConfig) -> Any:
    """Return the current working directory for the configured agent sandbox."""
    sandbox = _sandbox_from_config(config)
    _log_started("pwd", sandbox.sandbox_id)
    try:
        ret = await sandbox.pwd()
    except Exception:
        _log_failed("pwd", sandbox.sandbox_id)
        raise
    _log_completed("pwd", sandbox.sandbox_id)
    return ret


@tool(
    args_schema=CdArgs,
    description=t("tools.sandbox.cd.description"),
)
async def cd(path: str, runtime: ToolRuntime) -> Any:
    """Change the current working directory for the configured agent sandbox."""
    sandbox = _sandbox_from_runtime(runtime)
    _log_started("cd", sandbox.sandbox_id)
    try:
        ret = await sandbox.cd(path)
    except Exception:
        _log_failed("cd", sandbox.sandbox_id)
        raise
    _log_completed("cd", sandbox.sandbox_id)
    return ret


def _result_exit_code(result: Any) -> Any:
    if isinstance(result, dict):
        return result.get("exit_code")
    return getattr(result, "exit_code", None)


def _sandbox_from_runtime(runtime: ToolRuntime) -> AgentSandbox:
    return runtime.config["configurable"]["sandbox"]


def _sandbox_from_config(config: RunnableConfig) -> AgentSandbox:
    return config["configurable"]["sandbox"]


def _log_started(tool_name: str, sandbox_id: str | None) -> None:
    logger.info(t("tools.sandbox.started"), tool_name, sandbox_id)


def _log_completed(tool_name: str, sandbox_id: str | None) -> None:
    logger.info(t("tools.sandbox.completed"), tool_name, sandbox_id)


def _log_failed(tool_name: str, sandbox_id: str | None) -> None:
    logger.exception(t("tools.sandbox.failed"), tool_name, sandbox_id)


def _log_run_command_started(sandbox_id: str | None, command: str) -> None:
    logger.info(
        t("tools.sandbox.run_command.started"),
        sandbox_id,
        len(command),
    )


def _log_run_command_completed(sandbox_id: str | None, result: Any) -> None:
    logger.info(
        t("tools.sandbox.run_command.completed"),
        sandbox_id,
        _result_exit_code(result),
    )


def _log_run_command_failed(sandbox_id: str | None, command: str) -> None:
    logger.exception(
        t("tools.sandbox.run_command.failed"),
        sandbox_id,
        len(command),
    )


SandboxTools = [
    run_command,
    write_file,
    read_file,
    list_files,
    delete_file,
    copy,
    rename,
    pwd,
    cd,
]
