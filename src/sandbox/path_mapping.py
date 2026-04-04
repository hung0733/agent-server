from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


VIRTUAL_WORKSPACE_ROOT = Path("/mnt/data/workspace")
VIRTUAL_UPLOADS_ROOT = Path("/mnt/data/uploads")
VIRTUAL_OUTPUTS_ROOT = Path("/mnt/data/outputs")
VIRTUAL_SKILLS_ROOT = Path("/mnt/skills")

_VIRTUAL_ROOTS = {
    VIRTUAL_WORKSPACE_ROOT: Path("/workspace/mnt/data/workspace"),
    VIRTUAL_UPLOADS_ROOT: Path("/workspace/mnt/data/uploads"),
    VIRTUAL_OUTPUTS_ROOT: Path("/workspace/mnt/data/outputs"),
    VIRTUAL_SKILLS_ROOT: Path("/mnt/skills"),
}


@dataclass(frozen=True)
class ResolvedSandboxPath:
    host_path: Path
    container_path: Path
    virtual_path: Path


class SandboxPathMapper:
    def __init__(self, host_root: Path, owner_id: str) -> None:
        self.host_root = host_root.resolve()
        self.owner_id = owner_id
        self.owner_root = (self.host_root / owner_id).resolve()

    @classmethod
    def for_local_owner(cls, host_root: Path, owner_id: str) -> "SandboxPathMapper":
        return cls(host_root, owner_id)

    def resolve_virtual_path(self, raw_path: str) -> ResolvedSandboxPath:
        path = Path(raw_path)
        for virtual_root, container_root in _VIRTUAL_ROOTS.items():
            try:
                relative = path.relative_to(virtual_root)
            except ValueError:
                continue
            host_path = (self.owner_root / Path(*virtual_root.parts[1:]) / relative).resolve()
            return ResolvedSandboxPath(
                host_path=host_path,
                container_path=(container_root / relative),
                virtual_path=(virtual_root / relative),
            )
        raise ValueError(f"唔支援的 sandbox path: {raw_path}")

    def display_path(self, path: str | Path) -> str:
        resolved = Path(path).resolve()
        try:
            relative = resolved.relative_to(self.owner_root)
        except ValueError:
            return str(path)
        relative_parts = relative.parts
        for virtual_root in _VIRTUAL_ROOTS:
            virtual_parts = virtual_root.parts[1:]
            if relative_parts[: len(virtual_parts)] == virtual_parts:
                return str(Path("/") / relative)
        return str(VIRTUAL_WORKSPACE_ROOT / relative)
