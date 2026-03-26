"""
SimpleMem - Multi-Agent Memory System
支援多 agent 隔離、跨 session 共享記憶

Architecture:
- PostgreSQL: 存儲原始對話 (dialogues 表)
- Qdrant: 存儲壓縮後的記憶 (vector embeddings + metadata)
- Agent 完全隔離 (agent_id filtering)
- 同一 agent 所有 sessions 共享記憶
"""
from typing import List, Optional, Dict
import uuid
import asyncio
import asyncpg
from qdrant_client import QdrantClient

from .models.memory_entry import Dialogue, MemoryEntry
from .utils.llm_client import LLMClient
from .utils.embedding import EmbeddingModel
from .database.vector_store import QdrantVectorStore
from .database.pg_store import PostgreSQLStore
from .core.memory_builder import MemoryBuilder
from .core.hybrid_retriever import HybridRetriever
from .core.answer_generator import AnswerGenerator
from . import config


class MultiAgentMemorySystem:
    """
    Multi-Agent Memory System with Cross-Session Shared Memory

    Features:
    - Agent isolation via agent_id
    - Cross-session memory sharing (per agent)
    - Session tracking (no expiry, manual finalize)
    - Context fetched from DB (not RAM)

    Database:
    - PostgreSQL: dialogues table
    - Qdrant: memory entries (single collection with agent_id filtering)
    """

    def __init__(
        self,
        agent_id: str,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        # Database configuration
        qdrant_url: Optional[str] = None,
        qdrant_api_key: Optional[str] = None,
        postgres_url: Optional[str] = None,
        # LLM parameters
        enable_thinking: Optional[bool] = None,
        use_streaming: Optional[bool] = None,
        # Retrieval parameters
        enable_planning: Optional[bool] = None,
        enable_reflection: Optional[bool] = None,
        max_reflection_rounds: Optional[int] = None,
        # Processing parameters
        enable_parallel_processing: Optional[bool] = None,
        max_parallel_workers: Optional[int] = None,
        enable_parallel_retrieval: Optional[bool] = None,
        max_retrieval_workers: Optional[int] = None
    ):
        """
        初始化 Multi-Agent Memory System

        Args:
            agent_id: Agent UUID (string format)
            qdrant_url: Qdrant server URL
            qdrant_api_key: Qdrant API key (optional)
            postgres_url: PostgreSQL connection URL
            (其他參數與原 SimpleMemSystem 相同)
        """
        self.agent_id = agent_id
        self._initialized = False

        # Store initialization parameters
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.qdrant_url = qdrant_url
        self.qdrant_api_key = qdrant_api_key
        self.postgres_url = postgres_url
        self.enable_thinking = enable_thinking
        self.use_streaming = use_streaming
        self.enable_planning = enable_planning
        self.enable_reflection = enable_reflection
        self.max_reflection_rounds = max_reflection_rounds
        self.enable_parallel_processing = enable_parallel_processing
        self.max_parallel_workers = max_parallel_workers
        self.enable_parallel_retrieval = enable_parallel_retrieval
        self.max_retrieval_workers = max_retrieval_workers

    async def initialize(self):
        """Async initialization of database connections and components"""
        if self._initialized:
            return

        print("=" * 60)
        print("Initializing Multi-Agent SimpleMem System")
        print(f"Agent ID: {self.agent_id}")
        print("=" * 60)

        # Database connections
        qdrant_url = self.qdrant_url or config.QDRANT_URL
        postgres_url = self.postgres_url or config.POSTGRES_URL

        print(f"\n📊 Connecting to Qdrant: {qdrant_url}")
        self.qdrant_client = QdrantClient(
            url=qdrant_url,
            api_key=self.qdrant_api_key or config.QDRANT_API_KEY
        )

        print(f"📊 Connecting to PostgreSQL...")
        self.pg_pool = await asyncpg.create_pool(postgres_url)

        # Initialize core components
        print(f"\n🔧 Initializing core components...")

        self.llm_client = LLMClient(
            api_key=self.api_key,
            model=self.model,
            base_url=self.base_url,
            enable_thinking=self.enable_thinking,
            use_streaming=self.use_streaming
        )

        self.embedding_model = EmbeddingModel()

        self.vector_store = QdrantVectorStore(
            client=self.qdrant_client,
            agent_id=self.agent_id,
            embedding_model=self.embedding_model
        )

        self.pg_store = PostgreSQLStore(pool=self.pg_pool)

        # Initialize three major modules
        self.memory_builder = MemoryBuilder(
            llm_client=self.llm_client,
            vector_store=self.vector_store,
            enable_parallel_processing=self.enable_parallel_processing,
            max_parallel_workers=self.max_parallel_workers
        )

        self.hybrid_retriever = HybridRetriever(
            llm_client=self.llm_client,
            vector_store=self.vector_store,
            enable_planning=self.enable_planning,
            enable_reflection=self.enable_reflection,
            max_reflection_rounds=self.max_reflection_rounds,
            enable_parallel_retrieval=self.enable_parallel_retrieval,
            max_retrieval_workers=self.max_retrieval_workers
        )

        self.answer_generator = AnswerGenerator(
            llm_client=self.llm_client
        )

        self._initialized = True
        print("\n✅ System initialization complete!")
        print("=" * 60)

    async def add_dialogue(
        self,
        session_id: str,
        speaker: str,
        content: str,
        timestamp: Optional[str] = None
    ):
        """
        Add a dialogue to a session

        Args:
            session_id: Session UUID (string format)
            speaker: Speaker name
            content: Dialogue content
            timestamp: Timestamp (ISO 8601 format, optional)
        """
        if not self._initialized:
            raise RuntimeError("System not initialized. Call initialize() first.")

        # Store to PostgreSQL
        dialogue_id = await self.pg_store.add_dialogue(
            agent_id=self.agent_id,
            session_id=session_id,
            speaker=speaker,
            content=content,
            timestamp=timestamp
        )

        # Add to MemoryBuilder buffer
        dialogue = Dialogue(
            dialogue_id=dialogue_id,
            speaker=speaker,
            content=content,
            timestamp=timestamp
        )
        self.memory_builder.add_dialogue(dialogue, session_id=session_id, auto_process=True)

    async def finalize(self, session_id: str):
        """
        Finalize a session - process remaining dialogues and store to Qdrant

        Args:
            session_id: Session UUID to finalize
        """
        if not self._initialized:
            raise RuntimeError("System not initialized. Call initialize() first.")

        print(f"\n🔄 Finalizing session: {session_id}")

        # Process remaining dialogues in buffer
        entries = self.memory_builder.process_remaining(session_id=session_id)

        if entries:
            # Set agent_id and session_id for all entries
            for entry in entries:
                entry.agent_id = self.agent_id
                if not entry.session_id:
                    entry.session_id = session_id

            # Store to Qdrant
            self.vector_store.add_entries(entries)
            print(f"✅ Finalized session with {len(entries)} memory entries")
        else:
            print("✅ Session finalized (no new entries)")

    async def ask(self, question: str) -> str:
        """
        Ask a question - retrieves from ALL sessions of this agent

        Args:
            question: User question

        Returns:
            Answer string
        """
        if not self._initialized:
            raise RuntimeError("System not initialized. Call initialize() first.")

        print("\n" + "=" * 60)
        print(f"Question: {question}")
        print("=" * 60)

        # Stage 3: Intent-Aware Retrieval Planning
        # Retrieves from all sessions of this agent (agent_id filtering in vector_store)
        contexts = self.hybrid_retriever.retrieve(question)

        # Generate answer from retrieved context
        answer = self.answer_generator.generate_answer(question, contexts)

        print("\nAnswer:")
        print(answer)
        print("=" * 60 + "\n")

        return answer

    async def get_all_memories(self) -> List[MemoryEntry]:
        """
        Get all memory entries for this agent (across all sessions)
        """
        if not self._initialized:
            raise RuntimeError("System not initialized. Call initialize() first.")

        return self.vector_store.get_all_entries()

    async def get_session_dialogues(self, session_id: str) -> List[Dict]:
        """
        Get all dialogues for a specific session

        Args:
            session_id: Session UUID

        Returns:
            List of dialogue dictionaries
        """
        if not self._initialized:
            raise RuntimeError("System not initialized. Call initialize() first.")

        return await self.pg_store.get_dialogues(
            agent_id=self.agent_id,
            session_id=session_id
        )

    async def get_all_sessions(self) -> List[str]:
        """
        Get all session IDs for this agent

        Returns:
            List of session UUID strings
        """
        if not self._initialized:
            raise RuntimeError("System not initialized. Call initialize() first.")

        return await self.pg_store.get_sessions(agent_id=self.agent_id)

    async def print_memories(self):
        """
        Print all memory entries for this agent (for debugging)
        """
        memories = await self.get_all_memories()
        print("\n" + "=" * 60)
        print(f"All Memory Entries for Agent {self.agent_id} ({len(memories)} total)")
        print("=" * 60)

        for i, memory in enumerate(memories, 1):
            print(f"\n[Entry {i}]")
            print(f"ID: {memory.entry_id}")
            print(f"Session: {memory.session_id}")
            print(f"Restatement: {memory.lossless_restatement}")
            if memory.timestamp:
                print(f"Time: {memory.timestamp}")
            if memory.location:
                print(f"Location: {memory.location}")
            if memory.persons:
                print(f"Persons: {', '.join(memory.persons)}")
            if memory.entities:
                print(f"Entities: {', '.join(memory.entities)}")
            if memory.topic:
                print(f"Topic: {memory.topic}")
            print(f"Keywords: {', '.join(memory.keywords)}")

        print("\n" + "=" * 60)

    async def close(self):
        """
        Close database connections and cleanup resources
        """
        if self.pg_pool:
            await self.pg_pool.close()
            print("✅ Database connections closed")


# Convenience function
async def create_system(
    agent_id: str,
    enable_planning: Optional[bool] = None,
    enable_reflection: Optional[bool] = None,
    max_reflection_rounds: Optional[int] = None,
    enable_parallel_processing: Optional[bool] = None,
    max_parallel_workers: Optional[int] = None,
    enable_parallel_retrieval: Optional[bool] = None,
    max_retrieval_workers: Optional[int] = None
) -> MultiAgentMemorySystem:
    """
    Create and initialize Multi-Agent Memory System instance

    Args:
        agent_id: Agent UUID (string format)
        (other parameters use config.py defaults when None)

    Returns:
        Initialized MultiAgentMemorySystem instance
    """
    system = MultiAgentMemorySystem(
        agent_id=agent_id,
        enable_planning=enable_planning,
        enable_reflection=enable_reflection,
        max_reflection_rounds=max_reflection_rounds,
        enable_parallel_processing=enable_parallel_processing,
        max_parallel_workers=max_parallel_workers,
        enable_parallel_retrieval=enable_parallel_retrieval,
        max_retrieval_workers=max_retrieval_workers
    )
    await system.initialize()
    return system
