from __future__ import annotations

from pathlib import Path

import pytest

from sandbox.path_mapping import (
    VIRTUAL_OUTPUTS_ROOT,
    VIRTUAL_SKILLS_ROOT,
    VIRTUAL_UPLOADS_ROOT,
    VIRTUAL_WORKSPACE_ROOT,
    SandboxPathMapper,
)


def test_virtual_workspace_maps_to_container_and_host_paths(tmp_path):
    mapper = SandboxPathMapper.for_local_owner(tmp_path / "agent-home", "user-1")

    resolved = mapper.resolve_virtual_path(f"{VIRTUAL_WORKSPACE_ROOT}/project/app.py")

    assert resolved.host_path == (tmp_path / "agent-home" / "user-1" / "mnt/data/workspace/project/app.py").resolve()
    assert resolved.container_path == Path("/workspace/mnt/data/workspace/project/app.py")


def test_display_path_redacts_real_host_root(tmp_path):
    mapper = SandboxPathMapper.for_local_owner(tmp_path / "agent-home", "user-1")
    real_path = tmp_path / "agent-home" / "user-1" / "mnt/data/workspace/project/app.py"

    assert mapper.display_path(real_path) == f"{VIRTUAL_WORKSPACE_ROOT}/project/app.py"


def test_rejects_non_whitelisted_virtual_path(tmp_path):
    mapper = SandboxPathMapper.for_local_owner(tmp_path / "agent-home", "user-1")

    with pytest.raises(ValueError, match="唔支援"):
        mapper.resolve_virtual_path("/etc/passwd")


def test_known_virtual_roots_are_exposed():
    assert str(VIRTUAL_WORKSPACE_ROOT).startswith("/")
    assert str(VIRTUAL_UPLOADS_ROOT).startswith("/")
    assert str(VIRTUAL_OUTPUTS_ROOT).startswith("/")
    assert str(VIRTUAL_SKILLS_ROOT).startswith("/")
