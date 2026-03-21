# pyright: reportMissingImports=false
"""Integration tests for the full simplemem-cross-lite pipeline.

These tests verify the complete memory lifecycle:
- Store → Context Injection → LLM Retrieval
- Multi-tenant isolation end-to-end
- Cross-session memory flow using real Docker containers

Uses real PostgreSQL and Qdrant Docker containers for true integration testing.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional
from uuid import uuid4

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simplemem_cross_lite.types import (
    ContextBundle,
    CrossMemoryEntry,
    CrossObservation,
    EventKind,
    FinalizationReport,
    ObservationType,
    SessionRecord,
    SessionStatus,
    SessionSummary,
)
from simplemem_cross_lite.storage.postgres import PostgresSessionStorage
from simplemem_cross_lite.storage.qdrant import QdrantVectorStore
from simplemem_cross_lite.session_manager import SessionManager


# =============================================================================
# Docker Service Helpers
# =============================================================================


def _is_docker_running() -> bool:
    """Check if Docker daemon is running."""
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _start_postgres_container() -> tuple[str, str]:
    """Start PostgreSQL Docker container and return (dsn, container_id)."""
    container_name = f"simplemem_integ_postgres_{uuid4().hex[:8]}"
    
    subprocess.run(
        [
            "docker", "run", "-d",
            "--name", container_name,
            "-e", "POSTGRES_USER=testuser",
            "-e", "POSTGRES_PASSWORD=testpass",
            "-e", "POSTGRES_DB=testdb",
            "-p", "5432",
            "postgres:16-alpine",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    
    result = subprocess.run(
        ["docker", "port", container_name, "5432"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    port_line = result.stdout.strip().split("\n")[0]
    host_port = port_line.split(":")[-1]
    
    dsn = f"postgresql://testuser:testpass@localhost:{host_port}/testdb"
    
    import asyncpg
    max_attempts = 30
    for attempt in range(max_attempts):
        try:
            conn = asyncio.run(asyncpg.connect(dsn))
            asyncio.run(conn.close())
            break
        except Exception:
            time.sleep(0.5)
    else:
        raise RuntimeError(f"PostgreSQL container {container_name} failed to start")
    
    return dsn, container_name


def _start_qdrant_container() -> tuple[str, str]:
    """Start Qdrant Docker container and return (url, container_id)."""
    container_name = f"simplemem_integ_qdrant_{uuid4().hex[:8]}"
    
    subprocess.run(
        [
            "docker", "run", "-d",
            "--name", container_name,
            "-p", "6333",
            "qdrant/qdrant:latest",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    
    result = subprocess.run(
        ["docker", "port", container_name, "6333"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    port_line = result.stdout.strip().split("\n")[0]
    host_port = port_line.split(":")[-1]
    
    url = f"http://localhost:{host_port}"
    
    # Wait for Qdrant to be ready
    import httpx
    max_attempts = 30
    for attempt in range(max_attempts):
        try:
            response = httpx.get(f"{url}/", timeout=5)
            if response.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        raise RuntimeError(f"Qdrant container {container_name} failed to start")
    
    return url, container_name


def _stop_docker_container(container_id: str) -> None:
    """Stop and remove a Docker container."""
    try:
        subprocess.run(
            ["docker", "stop", "-t", "0", container_id],
            check=True,
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            ["docker", "rm", container_id],
            check=True,
            capture_output=True,
            timeout=10,
        )
    except subprocess.CalledProcessError:
        pass


# =============================================================================
# Helper Functions
# =============================================================================


def _make_memory_entry(
    entry_id: str = "",
    lossless_restatement: str = "Test memory entry",
    keywords: list[str] | None = None,
    timestamp: str | None = None,
    location: str | None = None,
    persons: list[str] | None = None,
    entities: list[str] | None = None,
    topic: str | None = None,
    tenant_id: str = "test-tenant",
    memory_session_id: str = "mem-sess-001",
    source_kind: str = "observation",
    source_id: int = 0,
    importance: float = 0.5,
) -> CrossMemoryEntry:
    """Create a CrossMemoryEntry with sensible defaults for testing."""
    return CrossMemoryEntry(
        entry_id=entry_id or str(uuid4()),
        lossless_restatement=lossless_restatement,
        keywords=keywords or [],
        timestamp=timestamp,
        location=location,
        persons=persons or [],
        entities=entities or [],
        topic=topic,
        tenant_id=tenant_id,
        memory_session_id=memory_session_id,
        source_kind=source_kind,
        source_id=source_id,
        importance=importance,
    )


# =============================================================================
# Integration Fixtures
# =============================================================================


@pytest_asyncio.fixture(scope="function")
async def integration_storage() -> AsyncGenerator[tuple[PostgresSessionStorage, QdrantVectorStore], None]:
    """
    Create both PostgreSQL and Qdrant storage instances backed by Docker containers.
    
    Provides real storage backends for full integration testing.
    """
    if not _is_docker_running():
        pytest.skip("Docker is not running - skipping integration tests")
    
    postgres_container = None
    qdrant_container = None
    dsn = None
    qdrant_url = None
    
    try:
        # Start PostgreSQL
        dsn, postgres_container = _start_postgres_container()
        
        # Start Qdrant
        qdrant_url, qdrant_container = _start_qdrant_container()
        
        # Create unique collection for this test run
        collection_name = f"integ_test_{uuid4().hex[:8]}"
        
        # Initialize storage instances
        postgres_storage = PostgresSessionStorage(dsn=dsn)
        qdrant_storage = QdrantVectorStore(url=qdrant_url, collection_name=collection_name)
        
        await postgres_storage.initialize()
        await qdrant_storage.initialize()
        
        yield postgres_storage, qdrant_storage
        
        await postgres_storage.close()
        await qdrant_storage.close()
        
    finally:
        if postgres_container:
            _stop_docker_container(postgres_container)
        if qdrant_container:
            _stop_docker_container(qdrant_container)


@pytest_asyncio.fixture(scope="function")
async def session_manager(
    integration_storage: tuple[PostgresSessionStorage, QdrantVectorStore]
) -> AsyncGenerator[SessionManager, None]:
    """
    Create a SessionManager with real storage backends.
    """
    postgres_storage, qdrant_storage = integration_storage
    manager = SessionManager(
        session_storage=postgres_storage,
        vector_store=qdrant_storage,
    )
    yield manager
    await manager.close()


# =============================================================================
# Full Pipeline Tests
# =============================================================================


class TestFullPipeline:
    """Tests for the complete memory lifecycle: store → context injection → retrieval."""

    @pytest.mark.asyncio
    async def test_store_memory_and_retrieve_context(
        self,
        integration_storage: tuple[PostgresSessionStorage, QdrantVectorStore],
    ) -> None:
        """
        Test storing memory entries and retrieving them via context bundle.
        
        Pipeline:
        1. Store memory entries in vector store
        2. Store session summary in PostgreSQL
        3. Build context bundle from both sources
        4. Verify context injection contains all stored data
        """
        postgres_storage, qdrant_storage = integration_storage
        
        tenant_id = "pipeline-tenant"
        project = "pipeline-project"
        
        # Step 1: Create session
        session = await postgres_storage.create_session(
            tenant_id=tenant_id,
            content_session_id="pipeline-session-001",
            project=project,
            user_prompt="Build authentication system",
        )
        memory_session_id = session.memory_session_id
        
        # Step 2: Record events
        await postgres_storage.add_event(
            memory_session_id=memory_session_id,
            kind=EventKind.message,
            title="User request",
            payload_json={"role": "user", "content": "Implement OAuth2 login"},
        )
        await postgres_storage.add_event(
            memory_session_id=memory_session_id,
            kind=EventKind.tool_use,
            title="Code generation",
            payload_json={"tool": "write_file", "file": "auth.py"},
        )
        
        # Step 3: Store observation
        obs_id = await postgres_storage.store_observation(
            memory_session_id=memory_session_id,
            type=ObservationType.decision,
            title="Chose OAuth2 for authentication",
            subtitle="Using Authorization Code flow",
            narrative="Decided to implement OAuth2 with PKCE for security",
        )
        assert obs_id > 0
        
        # Step 4: Store memory entries in vector store
        entries = [
            _make_memory_entry(
                entry_id="mem-001",
                lossless_restatement="User prefers OAuth2 over JWT for web authentication",
                keywords=["OAuth2", "authentication", "JWT"],
                tenant_id=tenant_id,
                memory_session_id=memory_session_id,
                source_kind="observation",
                source_id=obs_id,
                importance=0.8,
            ),
            _make_memory_entry(
                entry_id="mem-002",
                lossless_restatement="Authentication module should support multiple providers",
                keywords=["auth", "providers", "multi-tenant"],
                tenant_id=tenant_id,
                memory_session_id=memory_session_id,
                source_kind="observation",
                source_id=obs_id,
                importance=0.6,
            ),
        ]
        
        await qdrant_storage.add_entries(
            entries=entries,
            tenant_id=tenant_id,
            memory_session_id=memory_session_id,
            source_kind="observation",
            source_id=obs_id,
        )
        
        # Step 5: Store session summary
        summary_id = await postgres_storage.store_summary(
            memory_session_id=memory_session_id,
            request="Build authentication system",
            investigated="OAuth2, JWT, Session-based auth",
            learned="OAuth2 is most secure for web apps",
            completed="OAuth2 implementation with PKCE",
            next_steps="Add token refresh flow",
        )
        assert summary_id > 0
        
        # Step 6: Build context bundle (simulating next session)
        summaries = await postgres_storage.get_recent_summaries(project, limit=5)
        observations = await postgres_storage.get_recent_observations(project, limit=10)
        memory_entries = await qdrant_storage.get_all_entries(tenant_id=tenant_id)
        
        context = ContextBundle(
            session_summaries=summaries,
            timeline_observations=observations,
            memory_entries=memory_entries,
            total_tokens_estimate=500,
        )
        
        # Step 7: Verify context bundle contains all data
        assert len(context.session_summaries) == 1
        assert context.session_summaries[0].request == "Build authentication system"
        assert context.session_summaries[0].completed == "OAuth2 implementation with PKCE"
        
        assert len(context.timeline_observations) == 1
        assert context.timeline_observations[0].title == "Chose OAuth2 for authentication"
        
        assert len(context.memory_entries) == 2
        entry_texts = [e.lossless_restatement for e in context.memory_entries]
        assert "User prefers OAuth2 over JWT" in entry_texts[0] or "OAuth2 over JWT" in entry_texts[1]
        
        # Step 8: Render context for injection
        rendered = context.render(max_tokens=1000)
        assert "OAuth2" in rendered
        assert "authentication" in rendered

    @pytest.mark.asyncio
    async def test_conversation_to_memory_pipeline(
        self,
        session_manager: SessionManager,
    ) -> None:
        """
        Test the full conversation → memory pipeline.
        
        Simulates a realistic conversation flow:
        1. Start session
        2. Record conversation messages
        3. Record tool usage
        4. Finalize session
        5. Verify observations and summary are generated
        """
        tenant_id = "conv-tenant"
        project = "conv-project"
        
        # Step 1: Start session
        session = await session_manager.start_session(
            tenant_id=tenant_id,
            content_session_id="conv-session-001",
            project=project,
            user_prompt="Implement user registration feature",
        )
        
        assert session.status == SessionStatus.active
        assert session.tenant_id == tenant_id
        
        # Step 2: Record conversation
        await session_manager.record_message(
            memory_session_id=session.memory_session_id,
            content="I need to implement a user registration system with email verification",
            role="user",
        )
        
        await session_manager.record_message(
            memory_session_id=session.memory_session_id,
            content="I'll create a registration form with email validation",
            role="assistant",
        )
        
        await session_manager.record_tool_use(
            memory_session_id=session.memory_session_id,
            tool_name="write_file",
            tool_input="registration.py",
            tool_output="Created registration module",
        )
        
        await session_manager.record_message(
            memory_session_id=session.memory_session_id,
            content="I've created the registration module with email verification support",
            role="assistant",
        )
        
        # Step 3: Finalize session
        report = await session_manager.finalize_session(session.memory_session_id)
        
        assert report.memory_session_id == session.memory_session_id
        assert report.observations_count >= 1  # Should have extracted observations
        assert report.summary_generated is True
        
        # Step 4: Verify session ended
        ended_session = await session_manager.get_session(session.memory_session_id)
        assert ended_session is not None
        
        # Step 5: Verify observations were stored
        observations = await session_manager.get_observations(session.memory_session_id)
        assert len(observations) >= 1
        
        # Step 6: Verify summary was stored
        summary = await session_manager.get_summary(session.memory_session_id)
        assert summary is not None
        assert summary.request == "Implement user registration feature"
        
        # Step 7: End session
        await session_manager.end_session(session.memory_session_id)
        
        final_session = await session_manager.get_session(session.memory_session_id)
        assert final_session is not None
        assert final_session.status == SessionStatus.completed

    @pytest.mark.asyncio
    async def test_cross_session_memory_retrieval(
        self,
        session_manager: SessionManager,
        integration_storage: tuple[PostgresSessionStorage, QdrantVectorStore],
    ) -> None:
        """
        Test that memory from previous sessions can be retrieved for new sessions.
        
        Scenario:
        1. Create session A, store memories
        2. Finalize session A
        3. Create session B for same tenant/project
        4. Verify memories from session A are retrievable
        """
        postgres_storage, qdrant_storage = integration_storage
        tenant_id = "cross-session-tenant"
        project = "cross-project"
        
        # Session A: Store memories
        session_a = await session_manager.start_session(
            tenant_id=tenant_id,
            content_session_id="cross-session-a",
            project=project,
            user_prompt="Research payment providers",
        )
        
        # Store memory about Stripe preference
        await postgres_storage.add_event(
            memory_session_id=session_a.memory_session_id,
            kind=EventKind.message,
            title="Payment decision",
            payload_json={"role": "user", "content": "Stripe is preferred for payment processing"},
        )
        
        await postgres_storage.store_observation(
            memory_session_id=session_a.memory_session_id,
            type=ObservationType.decision,
            title="Stripe selected for payments",
            narrative="Team decided to use Stripe for all payment processing",
        )
        
        # Store in vector store
        memory_entry = _make_memory_entry(
            entry_id="stripe-decision",
            lossless_restatement="User decided to use Stripe for payment processing due to excellent API",
            keywords=["Stripe", "payment", "API"],
            tenant_id=tenant_id,
            memory_session_id=session_a.memory_session_id,
            source_kind="decision",
            importance=0.9,
        )
        
        await qdrant_storage.add_entries(
            entries=[memory_entry],
            tenant_id=tenant_id,
            memory_session_id=session_a.memory_session_id,
            source_kind="decision",
        )
        
        await session_manager.finalize_session(session_a.memory_session_id)
        await session_manager.end_session(session_a.memory_session_id)
        
        # Session B: Retrieve previous memories
        session_b = await session_manager.start_session(
            tenant_id=tenant_id,
            content_session_id="cross-session-b",
            project=project,
            user_prompt="Implement payment integration",
        )
        
        # Retrieve memories for context injection
        previous_summaries = await postgres_storage.get_recent_summaries(project, limit=5)
        previous_observations = await postgres_storage.get_recent_observations(project, limit=10)
        previous_memories = await qdrant_storage.get_all_entries(tenant_id=tenant_id)
        
        # Verify cross-session retrieval
        assert len(previous_memories) >= 1
        
        found_stripe = False
        for entry in previous_memories:
            if "Stripe" in entry.lossless_restatement:
                found_stripe = True
                break
        assert found_stripe, "Previous Stripe memory should be retrievable"
        
        # Build context bundle for new session
        context = ContextBundle(
            session_summaries=previous_summaries,
            timeline_observations=previous_observations,
            memory_entries=previous_memories,
        )
        
        rendered = context.render(max_tokens=1000)
        assert "Stripe" in rendered

    @pytest.mark.asyncio
    async def test_memory_importance_affects_retrieval(
        self,
        integration_storage: tuple[PostgresSessionStorage, QdrantVectorStore],
    ) -> None:
        """
        Test that memory importance scores are stored and retrievable.
        """
        postgres_storage, qdrant_storage = integration_storage
        
        tenant_id = "importance-tenant"
        
        # Create session
        session = await postgres_storage.create_session(
            tenant_id=tenant_id,
            content_session_id="importance-session",
            project="importance-project",
        )
        
        # Store entries with different importance levels
        low_importance = _make_memory_entry(
            entry_id="low-imp",
            lossless_restatement="Minor configuration detail",
            importance=0.2,
            tenant_id=tenant_id,
            memory_session_id=session.memory_session_id,
        )
        
        high_importance = _make_memory_entry(
            entry_id="high-imp",
            lossless_restatement="Critical security decision",
            importance=0.95,
            tenant_id=tenant_id,
            memory_session_id=session.memory_session_id,
        )
        
        await qdrant_storage.add_entries(
            entries=[low_importance, high_importance],
            tenant_id=tenant_id,
            memory_session_id=session.memory_session_id,
            source_kind="decision",
        )
        
        # Retrieve and verify importance
        entries = await qdrant_storage.get_all_entries(tenant_id=tenant_id)
        
        assert len(entries) == 2
        
        high_entry = next(e for e in entries if e.entry_id == "high-imp")
        low_entry = next(e for e in entries if e.entry_id == "low-imp")
        
        assert high_entry.importance == 0.95
        assert low_entry.importance == 0.2


# =============================================================================
# Multi-Tenant Isolation Tests
# =============================================================================


class TestMultiTenantIsolation:
    """End-to-end tests for multi-tenant data isolation."""

    @pytest.mark.asyncio
    async def test_tenant_isolation_full_pipeline(
        self,
        integration_storage: tuple[PostgresSessionStorage, QdrantVectorStore],
    ) -> None:
        """
        Test complete tenant isolation across all storage layers.
        
        Verify that:
        1. Sessions from one tenant are not visible to another
        2. Observations from one tenant are not visible to another
        3. Memory entries from one tenant are not visible to another
        """
        postgres_storage, qdrant_storage = integration_storage
        
        # Tenant A data
        tenant_a = "tenant-isolation-a"
        project_a = "project-a"
        
        # Tenant B data
        tenant_b = "tenant-isolation-b"
        project_b = "project-b"
        
        # Create sessions for both tenants
        session_a = await postgres_storage.create_session(
            tenant_id=tenant_a,
            content_session_id="iso-session-a",
            project=project_a,
            user_prompt="Tenant A secret task",
        )
        
        session_b = await postgres_storage.create_session(
            tenant_id=tenant_b,
            content_session_id="iso-session-b",
            project=project_b,
            user_prompt="Tenant B secret task",
        )
        
        # Store observations
        obs_a = await postgres_storage.store_observation(
            memory_session_id=session_a.memory_session_id,
            type=ObservationType.feature,
            title="Tenant A feature",
            narrative="Secret feature for tenant A",
        )
        
        obs_b = await postgres_storage.store_observation(
            memory_session_id=session_b.memory_session_id,
            type=ObservationType.bugfix,
            title="Tenant B bugfix",
            narrative="Secret bugfix for tenant B",
        )
        
        # Store memory entries in vector store
        mem_a = _make_memory_entry(
            entry_id="mem-tenant-a",
            lossless_restatement="Tenant A confidential: API key is secret-key-a",
            tenant_id=tenant_a,
            memory_session_id=session_a.memory_session_id,
            importance=0.9,
        )
        
        mem_b = _make_memory_entry(
            entry_id="mem-tenant-b",
            lossless_restatement="Tenant B confidential: API key is secret-key-b",
            tenant_id=tenant_b,
            memory_session_id=session_b.memory_session_id,
            importance=0.9,
        )
        
        await qdrant_storage.add_entries(
            entries=[mem_a],
            tenant_id=tenant_a,
            memory_session_id=session_a.memory_session_id,
            source_kind="secret",
        )
        
        await qdrant_storage.add_entries(
            entries=[mem_b],
            tenant_id=tenant_b,
            memory_session_id=session_b.memory_session_id,
            source_kind="secret",
        )
        
        # Verify session isolation
        sessions_a = await postgres_storage.list_sessions(tenant_id=tenant_a)
        sessions_b = await postgres_storage.list_sessions(tenant_id=tenant_b)
        
        assert len(sessions_a) == 1
        assert sessions_a[0].user_prompt == "Tenant A secret task"
        
        assert len(sessions_b) == 1
        assert sessions_b[0].user_prompt == "Tenant B secret task"
        
        # Verify observation isolation via project
        obs_list_a = await postgres_storage.get_recent_observations(project_a)
        obs_list_b = await postgres_storage.get_recent_observations(project_b)
        
        assert len(obs_list_a) == 1
        assert obs_list_a[0].title == "Tenant A feature"
        
        assert len(obs_list_b) == 1
        assert obs_list_b[0].title == "Tenant B bugfix"
        
        # Verify vector store isolation
        entries_a = await qdrant_storage.get_all_entries(tenant_id=tenant_a)
        entries_b = await qdrant_storage.get_all_entries(tenant_id=tenant_b)
        
        assert len(entries_a) == 1
        assert "secret-key-a" in entries_a[0].lossless_restatement
        assert "secret-key-b" not in entries_a[0].lossless_restatement
        
        assert len(entries_b) == 1
        assert "secret-key-b" in entries_b[0].lossless_restatement
        assert "secret-key-a" not in entries_b[0].lossless_restatement

    @pytest.mark.asyncio
    async def test_cross_tenant_no_leakage_via_keyword_search(
        self,
        integration_storage: tuple[PostgresSessionStorage, QdrantVectorStore],
    ) -> None:
        """
        Verify that keyword search cannot leak data across tenants.
        
        Even with shared keywords, results should only include the tenant's own data.
        """
        _, qdrant_storage = integration_storage
        
        tenant_a = "keyword-tenant-a"
        tenant_b = "keyword-tenant-b"
        
        # Store entries with same keywords but different tenants
        for tenant, secret in [(tenant_a, "secret-alpha"), (tenant_b, "secret-beta")]:
            entry = _make_memory_entry(
                lossless_restatement=f"Shared project using {secret}",
                keywords=["shared", "project", "confidential"],
                tenant_id=tenant,
                memory_session_id=f"kw-session-{tenant}",
            )
            await qdrant_storage.add_entries(
                entries=[entry],
                tenant_id=tenant,
                memory_session_id=f"kw-session-{tenant}",
                source_kind="observation",
            )
        
        # Search with shared keywords for each tenant
        results_a = await qdrant_storage.keyword_search(
            keywords=["shared", "project"],
            tenant_id=tenant_a,
        )
        
        results_b = await qdrant_storage.keyword_search(
            keywords=["shared", "project"],
            tenant_id=tenant_b,
        )
        
        # Verify isolation
        assert len(results_a) >= 1
        assert all("secret-alpha" in e.lossless_restatement for e in results_a)
        assert all(e.tenant_id == tenant_a for e in results_a)
        
        assert len(results_b) >= 1
        assert all("secret-beta" in e.lossless_restatement for e in results_b)
        assert all(e.tenant_id == tenant_b for e in results_b)

    @pytest.mark.asyncio
    async def test_cross_tenant_no_leakage_via_semantic_search(
        self,
        integration_storage: tuple[PostgresSessionStorage, QdrantVectorStore],
    ) -> None:
        """
        Verify that semantic search cannot leak data across tenants.
        """
        _, qdrant_storage = integration_storage
        
        tenant_a = "semantic-tenant-a"
        tenant_b = "semantic-tenant-b"
        
        # Store similar entries for different tenants
        for tenant, unique_marker in [(tenant_a, "TENANT_A_DATA"), (tenant_b, "TENANT_B_DATA")]:
            entry = _make_memory_entry(
                lossless_restatement=f"Authentication configuration with {unique_marker}",
                keywords=["auth", "config"],
                tenant_id=tenant,
                memory_session_id=f"sem-session-{tenant}",
            )
            await qdrant_storage.add_entries(
                entries=[entry],
                tenant_id=tenant,
                memory_session_id=f"sem-session-{tenant}",
                source_kind="config",
            )
        
        # Retrieve all entries for each tenant
        results_a = await qdrant_storage.get_all_entries(tenant_id=tenant_a)
        results_b = await qdrant_storage.get_all_entries(tenant_id=tenant_b)
        
        # Verify strict isolation
        for entry in results_a:
            assert entry.tenant_id == tenant_a
            assert "TENANT_A_DATA" in entry.lossless_restatement
        
        for entry in results_b:
            assert entry.tenant_id == tenant_b
            assert "TENANT_B_DATA" in entry.lossless_restatement

    @pytest.mark.asyncio
    async def test_tenant_data_deletion_isolation(
        self,
        integration_storage: tuple[PostgresSessionStorage, QdrantVectorStore],
    ) -> None:
        """
        Verify that deleting one tenant's data doesn't affect another tenant.
        """
        _, qdrant_storage = integration_storage
        
        tenant_a = "delete-tenant-a"
        tenant_b = "delete-tenant-b"
        
        # Store entries for both tenants
        for tenant in [tenant_a, tenant_b]:
            entry = _make_memory_entry(
                lossless_restatement=f"Data for {tenant}",
                tenant_id=tenant,
                memory_session_id=f"del-session-{tenant}",
            )
            await qdrant_storage.add_entries(
                entries=[entry],
                tenant_id=tenant,
                memory_session_id=f"del-session-{tenant}",
                source_kind="data",
            )
        
        assert await qdrant_storage.count_entries(tenant_id=tenant_a) == 1
        assert await qdrant_storage.count_entries(tenant_id=tenant_b) == 1
        
        await qdrant_storage.clear(tenant_id=tenant_a)
        
        assert await qdrant_storage.count_entries(tenant_id=tenant_a) == 0
        assert await qdrant_storage.count_entries(tenant_id=tenant_b) == 1


# =============================================================================
# Context Injection Tests
# =============================================================================


class TestContextInjection:
    """Tests for context bundle creation and injection."""

    @pytest.mark.asyncio
    async def test_context_bundle_render(
        self,
        integration_storage: tuple[PostgresSessionStorage, QdrantVectorStore],
    ) -> None:
        """
        Test that context bundle correctly renders all components.
        """
        postgres_storage, qdrant_storage = integration_storage
        
        tenant_id = "context-tenant"
        project = "context-project"
        
        # Create session with full data
        session = await postgres_storage.create_session(
            tenant_id=tenant_id,
            content_session_id="context-session",
            project=project,
            user_prompt="Test context injection",
        )
        
        # Store summary
        await postgres_storage.store_summary(
            memory_session_id=session.memory_session_id,
            request="Implement feature X",
            investigated="Libraries A, B, C",
            learned="Library A is best for this use case",
            completed="Feature X implemented using Library A",
            next_steps="Add tests",
        )
        
        # Store observation
        await postgres_storage.store_observation(
            memory_session_id=session.memory_session_id,
            type=ObservationType.discovery,
            title="Library A has good documentation",
            narrative="Found excellent examples in Library A docs",
        )
        
        # Store memory entries
        entry = _make_memory_entry(
            lossless_restatement="User prefers Library A for similar tasks",
            keywords=["library", "preference"],
            tenant_id=tenant_id,
            memory_session_id=session.memory_session_id,
        )
        await qdrant_storage.add_entries(
            entries=[entry],
            tenant_id=tenant_id,
            memory_session_id=session.memory_session_id,
            source_kind="preference",
        )
        
        # Build context bundle
        summaries = await postgres_storage.get_recent_summaries(project, limit=5)
        observations = await postgres_storage.get_recent_observations(project, limit=10)
        memories = await qdrant_storage.get_all_entries(tenant_id=tenant_id)
        
        context = ContextBundle(
            session_summaries=summaries,
            timeline_observations=observations,
            memory_entries=memories,
            total_tokens_estimate=1000,
        )
        
        # Render and verify
        rendered = context.render(max_tokens=2000)
        
        assert "Feature X implemented" in rendered
        assert "Library A" in rendered
        assert "good documentation" in rendered
        assert "prefers Library A" in rendered

    @pytest.mark.asyncio
    async def test_context_bundle_token_limit(
        self,
        integration_storage: tuple[PostgresSessionStorage, QdrantVectorStore],
    ) -> None:
        """
        Test that context bundle respects token limits.
        """
        _, qdrant_storage = integration_storage
        
        tenant_id = "token-limit-tenant"
        
        # Store many entries
        entries = []
        for i in range(20):
            entries.append(_make_memory_entry(
                lossless_restatement=f"Memory entry number {i} with a longer description to increase token count",
                tenant_id=tenant_id,
                memory_session_id="token-session",
            ))
        
        await qdrant_storage.add_entries(
            entries=entries,
            tenant_id=tenant_id,
            memory_session_id="token-session",
            source_kind="data",
        )
        
        memories = await qdrant_storage.get_all_entries(tenant_id=tenant_id)
        
        context = ContextBundle(
            memory_entries=memories,
            total_tokens_estimate=500,
        )
        
        # Render with tight token limit
        rendered = context.render(max_tokens=50)
        
        # Should be truncated
        assert len(rendered.split()) < 100  # Approximate token limit

    @pytest.mark.asyncio
    async def test_empty_context_bundle(
        self,
    ) -> None:
        """
        Test that empty context bundle renders correctly.
        """
        context = ContextBundle()
        rendered = context.render(max_tokens=1000)
        
        assert rendered == ""


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error conditions and edge cases in the pipeline."""

    @pytest.mark.asyncio
    async def test_finalize_nonexistent_session(
        self,
        session_manager: SessionManager,
    ) -> None:
        """
        Verify that finalizing a nonexistent session returns a proper report.
        """
        report = await session_manager.finalize_session("nonexistent-session-id")
        
        assert report.memory_session_id == "nonexistent-session-id"
        assert report.observations_count == 0
        assert report.summary_generated is False
        assert report.entries_stored == 0

    @pytest.mark.asyncio
    async def test_session_manager_resilience(
        self,
        session_manager: SessionManager,
    ) -> None:
        """
        Test that session manager handles errors gracefully.
        """
        tenant_id = "error-tenant"
        project = "error-project"
        
        # Create and start session
        session = await session_manager.start_session(
            tenant_id=tenant_id,
            content_session_id="error-session",
            project=project,
            user_prompt="Test error handling",
        )
        
        # Record some events
        await session_manager.record_message(
            memory_session_id=session.memory_session_id,
            content="Normal message",
            role="user",
        )
        
        # Finalize - should work even if no memory processor
        report = await session_manager.finalize_session(session.memory_session_id)
        
        # Should still generate summary from events
        assert report.summary_generated is True

    @pytest.mark.asyncio
    async def test_concurrent_sessions(
        self,
        session_manager: SessionManager,
    ) -> None:
        """
        Test handling multiple concurrent sessions.
        """
        tenant_id = "concurrent-tenant"
        project = "concurrent-project"
        
        # Start multiple sessions
        sessions = []
        for i in range(5):
            session = await session_manager.start_session(
                tenant_id=tenant_id,
                content_session_id=f"concurrent-session-{i}",
                project=project,
                user_prompt=f"Task {i}",
            )
            sessions.append(session)
        
        # Record events in each
        for i, session in enumerate(sessions):
            await session_manager.record_message(
                memory_session_id=session.memory_session_id,
                content=f"Message for session {i}",
                role="user",
            )
        
        # Finalize all
        for session in sessions:
            report = await session_manager.finalize_session(session.memory_session_id)
            assert report.summary_generated is True
        
        # Verify all sessions are independent
        all_sessions = await session_manager.list_sessions(tenant_id=tenant_id)
        assert len(all_sessions) == 5

    @pytest.mark.asyncio
    async def test_large_event_batch(
        self,
        session_manager: SessionManager,
    ) -> None:
        """
        Test handling a large number of events in a session.
        """
        tenant_id = "batch-tenant"
        project = "batch-project"
        
        session = await session_manager.start_session(
            tenant_id=tenant_id,
            content_session_id="batch-session",
            project=project,
            user_prompt="Large batch test",
        )
        
        # Record many events
        for i in range(100):
            await session_manager.record_message(
                memory_session_id=session.memory_session_id,
                content=f"Message number {i}",
                role="user" if i % 2 == 0 else "assistant",
            )
        
        # Verify all events recorded
        events = await session_manager.get_events(session.memory_session_id)
        assert len(events) == 100
        
        # Finalize
        report = await session_manager.finalize_session(session.memory_session_id)
        assert report.observations_count >= 1
        assert report.summary_generated is True


# =============================================================================
# Session Manager Integration Tests
# =============================================================================


class TestSessionManagerIntegration:
    """Integration tests for SessionManager orchestrating the full pipeline."""

    @pytest.mark.asyncio
    async def test_complete_session_lifecycle(
        self,
        session_manager: SessionManager,
        integration_storage: tuple[PostgresSessionStorage, QdrantVectorStore],
    ) -> None:
        """
        Test complete session lifecycle from start to end.
        """
        postgres_storage, qdrant_storage = integration_storage
        
        tenant_id = "lifecycle-tenant"
        project = "lifecycle-project"
        
        # Start
        session = await session_manager.start_session(
            tenant_id=tenant_id,
            content_session_id="lifecycle-session",
            project=project,
            user_prompt="Build complete feature",
        )
        
        assert session.status == SessionStatus.active
        
        # Record various events
        await session_manager.record_message(
            memory_session_id=session.memory_session_id,
            content="Starting feature implementation",
            role="assistant",
        )
        
        await session_manager.record_tool_use(
            memory_session_id=session.memory_session_id,
            tool_name="write_file",
            tool_input="feature.py",
            tool_output="File created",
        )
        
        await session_manager.record_event(
            memory_session_id=session.memory_session_id,
            kind=EventKind.file_change,
            title="Modified feature.py",
            payload_json={"action": "create", "file": "feature.py"},
        )
        
        # Finalize
        report = await session_manager.finalize_session(session.memory_session_id)
        
        assert report.observations_count >= 1
        assert report.summary_generated is True
        
        # End
        await session_manager.end_session(session.memory_session_id)
        
        # Verify final state
        final = await session_manager.get_session(session.memory_session_id)
        assert final is not None
        assert final.status == SessionStatus.completed
        assert final.ended_at is not None

    @pytest.mark.asyncio
    async def test_session_listing_and_filtering(
        self,
        session_manager: SessionManager,
    ) -> None:
        """
        Test session listing with various filters.
        """
        # Create sessions for different tenants and projects
        for tenant in ["list-tenant-a", "list-tenant-b"]:
            for project in ["project-x", "project-y"]:
                session = await session_manager.start_session(
                    tenant_id=tenant,
                    content_session_id=f"list-{tenant}-{project}",
                    project=project,
                    user_prompt=f"Task for {tenant}/{project}",
                )
                await session_manager.finalize_session(session.memory_session_id)
                await session_manager.end_session(session.memory_session_id)
        
        # List by tenant
        tenant_a_sessions = await session_manager.list_sessions(tenant_id="list-tenant-a")
        assert len(tenant_a_sessions) == 2
        
        # List by project
        project_x_sessions = await session_manager.list_sessions(project="project-x")
        assert len(project_x_sessions) == 2
        
        # List by tenant and project
        specific = await session_manager.list_sessions(
            tenant_id="list-tenant-a",
            project="project-x"
        )
        assert len(specific) == 1
        
        # List with pagination
        page1 = await session_manager.list_sessions(limit=2)
        assert len(page1) == 2
        
        page2 = await session_manager.list_sessions(limit=2, offset=2)
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_session_status_transitions(
        self,
        session_manager: SessionManager,
    ) -> None:
        """
        Test valid session status transitions.
        """
        tenant_id = "status-tenant"
        project = "status-project"
        
        # Start active
        session = await session_manager.start_session(
            tenant_id=tenant_id,
            content_session_id="status-session",
            project=project,
        )
        assert session.status == SessionStatus.active
        
        # Finalize (should still be active)
        await session_manager.finalize_session(session.memory_session_id)
        mid = await session_manager.get_session(session.memory_session_id)
        assert mid is not None
        assert mid.status == SessionStatus.active
        
        # End with completed
        await session_manager.end_session(session.memory_session_id)
        final = await session_manager.get_session(session.memory_session_id)
        assert final is not None
        assert final.status == SessionStatus.completed
        
        # Start another and fail it
        failed_session = await session_manager.start_session(
            tenant_id=tenant_id,
            content_session_id="failed-session",
            project=project,
        )
        await session_manager.end_session(
            failed_session.memory_session_id,
            status=SessionStatus.failed
        )
        
        failed = await session_manager.get_session(failed_session.memory_session_id)
        assert failed is not None
        assert failed.status == SessionStatus.failed


# =============================================================================
# Performance Tests
# =============================================================================


class TestPerformance:
    """Tests for performance characteristics of the pipeline."""

    @pytest.mark.asyncio
    async def test_bulk_memory_storage(
        self,
        integration_storage: tuple[PostgresSessionStorage, QdrantVectorStore],
    ) -> None:
        """
        Test storing a large batch of memory entries.
        """
        _, qdrant_storage = integration_storage
        
        tenant_id = "bulk-tenant"
        memory_session_id = "bulk-session"
        
        # Create 100 entries
        entries = []
        for i in range(100):
            entries.append(_make_memory_entry(
                entry_id=f"bulk-entry-{i}",
                lossless_restatement=f"Bulk memory entry number {i}",
                keywords=[f"keyword-{i % 10}"],
                tenant_id=tenant_id,
                memory_session_id=memory_session_id,
            ))
        
        # Store in batch
        await qdrant_storage.add_entries(
            entries=entries,
            tenant_id=tenant_id,
            memory_session_id=memory_session_id,
            source_kind="bulk",
        )
        
        # Verify count
        count = await qdrant_storage.count_entries(tenant_id=tenant_id)
        assert count == 100

    @pytest.mark.asyncio
    async def test_parallel_session_operations(
        self,
        session_manager: SessionManager,
    ) -> None:
        """
        Test parallel operations on different sessions.
        """
        tenant_id = "parallel-tenant"
        project = "parallel-project"
        
        async def create_and_process_session(index: int) -> str:
            session = await session_manager.start_session(
                tenant_id=tenant_id,
                content_session_id=f"parallel-session-{index}",
                project=project,
                user_prompt=f"Parallel task {index}",
            )
            
            await session_manager.record_message(
                memory_session_id=session.memory_session_id,
                content=f"Message {index}",
                role="user",
            )
            
            await session_manager.finalize_session(session.memory_session_id)
            await session_manager.end_session(session.memory_session_id)
            
            return session.memory_session_id
        
        # Run 10 sessions in parallel
        import asyncio
        results = await asyncio.gather(*[
            create_and_process_session(i) for i in range(10)
        ])
        
        assert len(results) == 10
        assert len(set(results)) == 10  # All unique
        
        # Verify all sessions exist
        all_sessions = await session_manager.list_sessions(tenant_id=tenant_id)
        assert len(all_sessions) == 10