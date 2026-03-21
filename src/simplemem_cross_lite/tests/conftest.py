# pyright: reportMissingImports=false
"""Shared pytest fixtures for simplemem-cross-lite tests."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Generator
from uuid import uuid4

import pytest
import pytest_asyncio

# Ensure simplemem_cross_lite imports resolve
# Add SimpleMem root to Python path (symlink enables underscore import)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simplemem_cross_lite.types import (
    CrossMemoryEntry,
    CrossObservation,
    EventKind,
    ObservationType,
    RedactionLevel,
    SessionEvent,
    SessionRecord,
    SessionStatus,
    SessionSummary,
)


# =============================================================================
# Docker Service Fixtures
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
    container_name = f"simplemem_test_postgres_{uuid4().hex[:8]}"
    
    # Start PostgreSQL container
    subprocess.run(
        [
            "docker", "run", "-d",
            "--name", container_name,
            "-e", "POSTGRES_USER=testuser",
            "-e", "POSTGRES_PASSWORD=testpass",
            "-e", "POSTGRES_DB=testdb",
            "-p", "5432",  # Random host port
            "postgres:16-alpine",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    
    # Get the mapped port
    result = subprocess.run(
        ["docker", "port", container_name, "5432"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    # Parse port from output like "0.0.0.0:54321\n"
    port_line = result.stdout.strip().split("\n")[0]
    host_port = port_line.split(":")[-1]
    
    dsn = f"postgresql://testuser:testpass@localhost:{host_port}/testdb"
    
    # Wait for PostgreSQL to be ready
    max_attempts = 30
    for attempt in range(max_attempts):
        try:
            import asyncpg
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
    container_name = f"simplemem_test_qdrant_{uuid4().hex[:8]}"
    
    # Start Qdrant container
    subprocess.run(
        [
            "docker", "run", "-d",
            "--name", container_name,
            "-p", "6333",  # Random host port
            "qdrant/qdrant:latest",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    
    # Get the mapped port
    result = subprocess.run(
        ["docker", "port", container_name, "6333"],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    
    # Parse port from output like "0.0.0.0:63330\n"
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
        pass  # Container may already be removed


# =============================================================================
# Storage Fixtures
# =============================================================================


@pytest_asyncio.fixture(scope="function")
async def postgres_storage() -> AsyncGenerator[PostgresSessionStorage, None]:
    """
    Create a PostgresSessionStorage instance backed by a Docker container.
    
    Provides a real PostgreSQL database for integration tests.
    Container is automatically started and stopped.
    """
    from simplemem_cross_lite.storage.postgres import PostgresSessionStorage
    
    if not _is_docker_running():
        pytest.skip("Docker is not running - skipping PostgreSQL integration tests")
    
    dsn = None
    container_id = None
    
    try:
        dsn, container_id = _start_postgres_container()
        storage = PostgresSessionStorage(dsn=dsn)
        await storage.initialize()
        yield storage
        await storage.close()
    finally:
        if container_id:
            _stop_docker_container(container_id)


@pytest_asyncio.fixture(scope="function")
async def qdrant_storage() -> AsyncGenerator[QdrantVectorStore, None]:
    """
    Create a QdrantVectorStore instance backed by a Docker container.
    
    Provides a real Qdrant vector database for integration tests.
    Container is automatically started and stopped.
    """
    from simplemem_cross_lite.storage.qdrant import QdrantVectorStore
    
    if not _is_docker_running():
        pytest.skip("Docker is not running - skipping Qdrant integration tests")
    
    url = None
    container_id = None
    
    try:
        url, container_id = _start_qdrant_container()
        storage = QdrantVectorStore(url=url)
        await storage.initialize()
        yield storage
        await storage.close()
    finally:
        if container_id:
            _stop_docker_container(container_id)


# =============================================================================
# Client Fixtures
# =============================================================================


@pytest.fixture
def llm_client() -> LLMClient:
    """
    Create an LLMClient instance for testing.
    
    Uses a mock API key and base URL. Tests should mock the actual HTTP calls
    or use a local LLM service.
    """
    from simplemem_cross_lite.clients.llm import LLMClient
    
    return LLMClient(
        api_key="test-api-key",
        base_url="http://localhost:1234/v1",  # Default local LLM port
        model="test-model",
    )


@pytest.fixture
def embedding_client() -> EmbeddingClient:
    """
    Create an EmbeddingClient instance for testing.
    
    Uses a mock API key and base URL. Tests should mock the actual HTTP calls
    or use a local embedding service.
    """
    from simplemem_cross_lite.clients.embedding import EmbeddingClient
    
    return EmbeddingClient(
        api_key="test-api-key",
        base_url="http://localhost:1234/v1",  # Default local LLM port
        model="test-embedding-model",
    )


# =============================================================================
# Sample Data Fixtures
# =============================================================================


@pytest.fixture
def sample_session_record() -> SessionRecord:
    """Return a SessionRecord populated with test data."""
    return SessionRecord(
        tenant_id="test-tenant",
        content_session_id="content-sess-001",
        memory_session_id="mem-sess-001",
        project="test-project",
        user_prompt="Implement feature X",
        started_at=datetime.now(timezone.utc),
        status=SessionStatus.active,
    )


@pytest.fixture
def sample_events() -> list[SessionEvent]:
    """Return a list of three SessionEvent objects covering different kinds."""
    now = datetime.now(timezone.utc)
    return [
        SessionEvent(
            memory_session_id="mem-sess-001",
            timestamp=now,
            kind=EventKind.message,
            title="User asked about auth",
            payload_json={"role": "user", "text": "How does auth work?"},
            redaction_level=RedactionLevel.none,
        ),
        SessionEvent(
            memory_session_id="mem-sess-001",
            timestamp=now,
            kind=EventKind.tool_use,
            title="Ran grep for auth module",
            payload_json={"tool": "grep", "query": "auth"},
            redaction_level=RedactionLevel.none,
        ),
        SessionEvent(
            memory_session_id="mem-sess-001",
            timestamp=now,
            kind=EventKind.file_change,
            title="Modified auth.py",
            payload_json={"file": "auth.py", "action": "edit"},
            redaction_level=RedactionLevel.none,
        ),
    ]


@pytest.fixture
def sample_memory_entries() -> list[CrossMemoryEntry]:
    """Return a list of CrossMemoryEntry objects for testing."""
    now = datetime.now(timezone.utc)
    return [
        CrossMemoryEntry(
            entry_id="entry-001",
            lossless_restatement="User will meet Bob at Starbucks tomorrow at 3pm",
            keywords=["meeting", "Bob", "Starbucks", "tomorrow"],
            timestamp="2025-01-15T15:00:00Z",
            location="Starbucks",
            persons=["User", "Bob"],
            entities=["Starbucks"],
            topic="Meeting with Bob",
            tenant_id="test-tenant",
            memory_session_id="mem-sess-001",
            source_kind="observation",
            source_id=1,
            importance=0.8,
        ),
        CrossMemoryEntry(
            entry_id="entry-002",
            lossless_restatement="User decided to use PostgreSQL for session storage",
            keywords=["PostgreSQL", "session", "storage", "database"],
            timestamp=now.isoformat(),
            persons=["User"],
            entities=["PostgreSQL"],
            topic="Database choice",
            tenant_id="test-tenant",
            memory_session_id="mem-sess-001",
            source_kind="decision",
            source_id=2,
            importance=0.6,
        ),
    ]


@pytest.fixture
def sample_observation() -> CrossObservation:
    """Return a CrossObservation populated with test data."""
    return CrossObservation(
        obs_id=1,
        memory_session_id="mem-sess-001",
        timestamp=datetime.now(timezone.utc),
        type=ObservationType.decision,
        title="Chose PostgreSQL for storage",
        subtitle="Multi-tenant session storage",
        facts_json={"database": "PostgreSQL", "reason": "async support"},
        narrative="The team decided to use PostgreSQL due to its robust async support",
        concepts_json=["async", "database", "storage"],
        files_json=["storage/postgres.py"],
        vector_ref="vec-001",
    )


@pytest.fixture
def sample_summary() -> SessionSummary:
    """Return a SessionSummary populated with test data."""
    return SessionSummary(
        summary_id=1,
        memory_session_id="mem-sess-001",
        timestamp=datetime.now(timezone.utc),
        request="Implement authentication",
        investigated="OAuth2, JWT tokens, session management",
        learned="JWT is stateless, sessions require server storage",
        completed="Auth middleware, token generation, validation",
        next_steps="Add refresh tokens, implement logout",
        vector_ref="vec-summary-001",
    )


# Import for fixture implementations
import asyncio

# Import storage classes for type hints
from simplemem_cross_lite.storage.postgres import PostgresSessionStorage
from simplemem_cross_lite.storage.qdrant import QdrantVectorStore

# Import client classes for type hints
from simplemem_cross_lite.clients.llm import LLMClient
from simplemem_cross_lite.clients.embedding import EmbeddingClient
