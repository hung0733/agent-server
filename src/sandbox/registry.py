from __future__ import annotations

from dataclasses import dataclass, field

from sandbox.models import SandboxHandle


@dataclass
class SandboxRegistry:
    active: dict[str, SandboxHandle] = field(default_factory=dict)
    idle: dict[str, SandboxHandle] = field(default_factory=dict)
