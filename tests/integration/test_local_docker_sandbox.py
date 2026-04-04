from __future__ import annotations

from pathlib import Path

from sandbox.backends.local_docker import LocalDockerBackend


def test_local_backend_workspace_path_is_persistent(tmp_path):
    backend = LocalDockerBackend(base_url="http://127.0.0.1", host_workspace_root=tmp_path)

    assert backend.workspace_host_path("user-1") == Path(tmp_path / "user-1").resolve()
