from __future__ import annotations

from abc import ABC, abstractmethod

from sandbox.models import SandboxHandle, SandboxRequest


class SandboxBackend(ABC):
    @abstractmethod
    async def discover(self, request: SandboxRequest) -> SandboxHandle | None:
        raise NotImplementedError

    @abstractmethod
    async def create(self, request: SandboxRequest) -> SandboxHandle:
        raise NotImplementedError

    @abstractmethod
    async def destroy(self, handle: SandboxHandle) -> None:
        raise NotImplementedError

    @abstractmethod
    async def exec(self, handle: SandboxHandle, command: str, cwd: str, timeout: int) -> str:
        raise NotImplementedError

    @abstractmethod
    async def start_process(self, handle: SandboxHandle, command: str, cwd: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def get_process(self, handle: SandboxHandle, process_handle: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def kill_process(self, handle: SandboxHandle, process_handle: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def read_file(self, handle: SandboxHandle, path: str, encoding: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def write_file(self, handle: SandboxHandle, path: str, content: str, encoding: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def edit_file(
        self,
        handle: SandboxHandle,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool,
        encoding: str,
    ) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def apply_patch(self, handle: SandboxHandle, patch: str, strip: int) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def grep_files(
        self,
        handle: SandboxHandle,
        pattern: str,
        path: str,
        recursive: bool,
        ignore_case: bool,
        include: str,
        max_results: int,
    ) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    async def find_files(self, handle: SandboxHandle, pattern: str, path: str, max_results: int) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    async def list_dir(self, handle: SandboxHandle, path: str, show_hidden: bool) -> dict:
        raise NotImplementedError
