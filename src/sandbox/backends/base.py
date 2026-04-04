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
