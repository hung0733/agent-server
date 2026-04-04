from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256


SandboxScope = str


@dataclass(frozen=True)
class SandboxMount:
    name: str
    source: str
    target: str
    read_only: bool = False

    def fingerprint(self) -> str:
        return f"{self.name}:{self.source}:{self.target}:{int(self.read_only)}"


@dataclass(frozen=True)
class SandboxRequest:
    owner_id: str
    scope: SandboxScope
    scope_key: str
    profile: str
    network_mode: str = "default"
    mounts: tuple[SandboxMount, ...] = ()

    @property
    def sandbox_id(self) -> str:
        digest = sha256()
        digest.update(self.owner_id.encode())
        digest.update(self.scope.encode())
        digest.update(self.scope_key.encode())
        digest.update(self.profile.encode())
        digest.update(self.network_mode.encode())
        for mount in self.mounts:
            digest.update(mount.fingerprint().encode())
        return digest.hexdigest()[:24]

    def model_copy(self) -> "SandboxRequest":
        return SandboxRequest(
            owner_id=self.owner_id,
            scope=self.scope,
            scope_key=self.scope_key,
            profile=self.profile,
            network_mode=self.network_mode,
            mounts=self.mounts,
        )


@dataclass
class SandboxHandle:
    sandbox_id: str
    owner_id: str
    scope: SandboxScope
    scope_key: str
    profile: str
    endpoint: str
    backend_type: str
    workspace_host_path: str
    workspace_container_path: str
    metadata: dict[str, str] = field(default_factory=dict)
