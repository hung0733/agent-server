from __future__ import annotations

import asyncio

from backend.sandbox.agent_sandbox import AgentSandbox


_sandboxes: dict[str, AgentSandbox] = {}
_locks: dict[str, asyncio.Lock] = {}


async def get_agent_sandbox(agent_id: str, user_id: str) -> AgentSandbox:
    lock = _locks.setdefault(agent_id, asyncio.Lock())
    async with lock:
        sandbox = _sandboxes.get(agent_id)
        if sandbox is not None and sandbox.sandbox_id is not None:
            return sandbox

        sandbox = AgentSandbox(user_id=user_id, agent_id=agent_id)
        await sandbox.create()
        _sandboxes[agent_id] = sandbox
        return sandbox
