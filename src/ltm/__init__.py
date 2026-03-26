"""
SimpleMem Multi-Agent Long-Term Memory System

A semantic lossless compression framework for efficient long-term memory
in LLM agents with multi-agent isolation and cross-session memory sharing.

Features:
- Complete agent isolation via agent_id
- Cross-session memory sharing (same agent)
- DB-based context retrieval (PostgreSQL + Qdrant)
- Async API with parallel processing support

Usage:
    from ltm.simplemem import MultiAgentMemorySystem, create_system

    async def main():
        agent_id = str(uuid.uuid4())
        system = await create_system(agent_id=agent_id)

        session_id = str(uuid.uuid4())
        await system.add_dialogue(
            session_id=session_id,
            speaker="User",
            content="Hello world"
        )
        await system.finalize(session_id)

        answer = await system.ask("What did the user say?")
        await system.close()
"""

from .simplemem import MultiAgentMemorySystem, create_system

__version__ = "2.0.0-multiagent"
__all__ = ["MultiAgentMemorySystem", "create_system"]
