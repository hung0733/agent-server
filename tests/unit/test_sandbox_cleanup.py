from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sandbox.cleanup import SandboxJanitor
from sandbox.models import SandboxHandle
from sandbox.registry import SandboxRegistry


def test_janitor_collects_idle_handles_past_cutoff():
    handle = SandboxHandle(
        sandbox_id="sandbox-1",
        owner_id="user-1",
        scope="session",
        scope_key="thread-1",
        profile="default",
        endpoint="http://sandbox.local",
        backend_type="fake",
        workspace_host_path="/tmp/host",
        workspace_container_path="/workspace",
        metadata={"last_used_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()},
    )
    registry = SandboxRegistry(idle={handle.sandbox_id: handle})

    expired = SandboxJanitor(idle_timeout_seconds=1800).expired_idle_handles(registry)

    assert [item.sandbox_id for item in expired] == ["sandbox-1"]
