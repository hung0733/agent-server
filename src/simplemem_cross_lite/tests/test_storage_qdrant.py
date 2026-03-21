# pyright: reportMissingImports=false
"""Unit tests for QdrantVectorStore — vector storage for cross-session memory.

Each test creates its own QdrantVectorStore backed by a Docker Qdrant container
(via pytest fixtures). These are real integration tests for the vector storage layer.

Key test areas:
- Add/retrieve memory entries
- Semantic search (vector similarity)
- Keyword search (BM25-style text matching)
- Structured search (metadata filtering)
- Tenant isolation via payload filtering
- Session-scoped retrieval
"""

from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from simplemem_cross_lite.storage.qdrant import QdrantVectorStore
from simplemem_cross_lite.types import CrossMemoryEntry


def _is_docker_running() -> bool:
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


def _start_qdrant_container() -> tuple[str, str]:
    container_name = f"simplemem_test_qdrant_{uuid4().hex[:8]}"
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
    
    import httpx
    for _ in range(30):
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


def _make_entry(
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
    importance: float = 0.5,
) -> CrossMemoryEntry:
    entry = CrossMemoryEntry(
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
        importance=importance,
    )
    return entry


def _generate_vector(dim: int = 384) -> list[float]:
    import hashlib

    seed = hashlib.sha256(str(uuid4()).encode()).digest()
    vector = []
    for i in range(dim):
        val = int.from_bytes(seed[i % 32 : i % 32 + 4], "big")
        vector.append((val / 2**31 - 0.5) * 2)
    return vector


@pytest_asyncio.fixture(scope="function")
async def storage() -> AsyncGenerator[QdrantVectorStore, None]:
    if not _is_docker_running():
        pytest.skip("Docker is not running - skipping Qdrant integration tests")

    url = None
    container_id = None

    try:
        url, container_id = _start_qdrant_container()
        collection_name = f"test_{uuid4().hex[:8]}"
        store = QdrantVectorStore(url=url, collection_name=collection_name)
        await store.initialize()
        yield store
        await store.close()
    finally:
        if container_id:
            _stop_docker_container(container_id)


class TestQdrantVectorStore:

    @pytest.mark.asyncio
    async def test_add_entries(self, storage: QdrantVectorStore) -> None:
        entries = [
            _make_entry(
                entry_id="entry-001",
                lossless_restatement="User will meet Bob at Starbucks tomorrow at 3pm",
                keywords=["meeting", "Bob", "Starbucks"],
                tenant_id="tenant-a",
                memory_session_id="sess-001",

            ),
            _make_entry(
                entry_id="entry-002",
                lossless_restatement="User decided to use PostgreSQL for storage",
                keywords=["PostgreSQL", "database"],
                tenant_id="tenant-a",
                memory_session_id="sess-001",

            ),
        ]

        await storage.add_entries(
            entries=entries,
            tenant_id="tenant-a",
            memory_session_id="sess-001",
            source_kind="observation",
        )

        count = await storage.count_entries()
        assert count == 2

    @pytest.mark.asyncio
    async def test_add_entries_with_importance(
        self, storage: QdrantVectorStore
    ) -> None:
        entry = _make_entry(
            entry_id="entry-imp",
            lossless_restatement="Critical security decision",
            tenant_id="tenant-b",
            memory_session_id="sess-002",

        )

        await storage.add_entries(
            entries=[entry],
            tenant_id="tenant-b",
            memory_session_id="sess-002",
            source_kind="decision",
            importance=0.9,
        )

        count = await storage.count_entries(tenant_id="tenant-b")
        assert count == 1

    @pytest.mark.asyncio
    async def test_count_entries_by_tenant(self, storage: QdrantVectorStore) -> None:
        for tenant in ["tenant-x", "tenant-y", "tenant-x"]:
            entry = _make_entry(
                tenant_id=tenant,
                memory_session_id=f"sess-{tenant}",

            )
            await storage.add_entries(
                entries=[entry],
                tenant_id=tenant,
                memory_session_id=f"sess-{tenant}",
                source_kind="observation",
            )

        assert await storage.count_entries(tenant_id="tenant-x") == 2
        assert await storage.count_entries(tenant_id="tenant-y") == 1
        assert await storage.count_entries(tenant_id="tenant-z") == 0

    @pytest.mark.asyncio
    async def test_count_entries_by_session(
        self, storage: QdrantVectorStore
    ) -> None:
        for session_id in ["sess-a", "sess-b", "sess-a"]:
            entry = _make_entry(
                tenant_id="tenant-main",
                memory_session_id=session_id,

            )
            await storage.add_entries(
                entries=[entry],
                tenant_id="tenant-main",
                memory_session_id=session_id,
                source_kind="observation",
            )

        assert await storage.count_entries(memory_session_id="sess-a") == 2
        assert await storage.count_entries(memory_session_id="sess-b") == 1

    @pytest.mark.asyncio
    async def test_tenant_isolation_add_and_retrieve(
        self, storage: QdrantVectorStore
    ) -> None:
        entry_a = _make_entry(
            entry_id="entry-tenant-a",
            lossless_restatement="Tenant A secret data",
            tenant_id="tenant-a",
            memory_session_id="sess-tenant-a",

        )
        entry_b = _make_entry(
            entry_id="entry-tenant-b",
            lossless_restatement="Tenant B secret data",
            tenant_id="tenant-b",
            memory_session_id="sess-tenant-b",

        )

        await storage.add_entries(
            entries=[entry_a],
            tenant_id="tenant-a",
            memory_session_id="sess-tenant-a",
            source_kind="observation",
        )
        await storage.add_entries(
            entries=[entry_b],
            tenant_id="tenant-b",
            memory_session_id="sess-tenant-b",
            source_kind="observation",
        )

        entries_a = await storage.get_all_entries(tenant_id="tenant-a")
        entries_b = await storage.get_all_entries(tenant_id="tenant-b")

        assert len(entries_a) == 1
        assert entries_a[0].entry_id == "entry-tenant-a"
        assert entries_a[0].lossless_restatement == "Tenant A secret data"

        assert len(entries_b) == 1
        assert entries_b[0].entry_id == "entry-tenant-b"
        assert entries_b[0].lossless_restatement == "Tenant B secret data"

        all_entries = await storage.get_all_entries()
        assert len(all_entries) == 2

    @pytest.mark.asyncio
    async def test_tenant_isolation_search(
        self, storage: QdrantVectorStore
    ) -> None:
        entry_a = _make_entry(
            lossless_restatement="Authentication flow with OAuth2",
            keywords=["auth", "OAuth2"],
            tenant_id="tenant-auth-a",
            memory_session_id="sess-auth-a",

        )
        entry_b = _make_entry(
            lossless_restatement="Authentication flow with JWT",
            keywords=["auth", "JWT"],
            tenant_id="tenant-auth-b",
            memory_session_id="sess-auth-b",

        )

        await storage.add_entries(
            entries=[entry_a, entry_b],
            tenant_id="tenant-auth-a",
            memory_session_id="sess-auth-a",
            source_kind="observation",
        )
        await storage.add_entries(
            entries=[entry_b],
            tenant_id="tenant-auth-b",
            memory_session_id="sess-auth-b",
            source_kind="observation",
        )

        results_a = await storage.keyword_search(
            keywords=["auth"], tenant_id="tenant-auth-a"
        )
        results_b = await storage.keyword_search(
            keywords=["auth"], tenant_id="tenant-auth-b"
        )

        assert all(e.tenant_id == "tenant-auth-a" for e in results_a)
        assert all(e.tenant_id == "tenant-auth-b" for e in results_b)

    @pytest.mark.asyncio
    async def test_tenant_isolation_clear(
        self, storage: QdrantVectorStore
    ) -> None:
        for tenant in ["tenant-clear-a", "tenant-clear-b"]:
            entry = _make_entry(
                tenant_id=tenant,
                memory_session_id=f"sess-clear-{tenant}",

            )
            await storage.add_entries(
                entries=[entry],
                tenant_id=tenant,
                memory_session_id=f"sess-clear-{tenant}",
                source_kind="observation",
            )

        await storage.clear(tenant_id="tenant-clear-a")

        assert await storage.count_entries(tenant_id="tenant-clear-a") == 0
        assert await storage.count_entries(tenant_id="tenant-clear-b") == 1

    @pytest.mark.asyncio
    async def test_semantic_search_vector(
        self, storage: QdrantVectorStore
    ) -> None:
        vector1 = [0.9] * 384
        vector2 = [0.1] * 384

        entry1 = _make_entry(
            entry_id="entry-similar",
            lossless_restatement="This entry is similar to the query",
            tenant_id="tenant-search",
            memory_session_id="sess-search",
        )
        entry1.vector = vector1  # type: ignore[attr-defined]

        entry2 = _make_entry(
            entry_id="entry-dissimilar",
            lossless_restatement="This entry is different from the query",
            tenant_id="tenant-search",
            memory_session_id="sess-search",
        )
        entry2.vector = vector2  # type: ignore[attr-defined]

        await storage.add_entries(
            entries=[entry1, entry2],
            tenant_id="tenant-search",
            memory_session_id="sess-search",
            source_kind="observation",
        )

        query_vector = [0.85] * 384
        results = await storage.semantic_search_vector(
            query_vector=query_vector,
            top_k=10,
            tenant_id="tenant-search",
        )

        assert len(results) == 2
        assert results[0].entry_id == "entry-similar"

    @pytest.mark.asyncio
    async def test_semantic_search_with_tenant_filter(
        self, storage: QdrantVectorStore
    ) -> None:
        vector = _generate_vector()

        for tenant in ["tenant-sem-a", "tenant-sem-b"]:
            entry = _make_entry(
                lossless_restatement=f"Entry for {tenant}",
                tenant_id=tenant,
                memory_session_id=f"sess-sem-{tenant}",
            )
            entry.vector = vector  # type: ignore[attr-defined]
            await storage.add_entries(
                entries=[entry],
                tenant_id=tenant,
                memory_session_id=f"sess-sem-{tenant}",
                source_kind="observation",
            )

        results = await storage.semantic_search_vector(
            query_vector=vector,
            top_k=10,
            tenant_id="tenant-sem-a",
        )

        assert len(results) == 1
        assert results[0].tenant_id == "tenant-sem-a"

    @pytest.mark.asyncio
    async def test_keyword_search_basic(
        self, storage: QdrantVectorStore
    ) -> None:
        entry1 = _make_entry(
            lossless_restatement="The authentication module handles OAuth2 login",
            keywords=["auth", "OAuth2"],
            tenant_id="tenant-kw",
            memory_session_id="sess-kw-1",

        )
        entry2 = _make_entry(
            lossless_restatement="Database connection pool configuration",
            keywords=["database", "pool"],
            tenant_id="tenant-kw",
            memory_session_id="sess-kw-2",

        )

        await storage.add_entries(
            entries=[entry1, entry2],
            tenant_id="tenant-kw",
            memory_session_id="sess-kw-1",
            source_kind="observation",
        )

        results = await storage.keyword_search(
            keywords=["OAuth2", "authentication"],
            top_k=5,
            tenant_id="tenant-kw",
        )

        assert any("OAuth2" in e.lossless_restatement for e in results)

    @pytest.mark.asyncio
    async def test_keyword_search_no_results(
        self, storage: QdrantVectorStore
    ) -> None:
        entry = _make_entry(
            lossless_restatement="Database configuration settings",
            tenant_id="tenant-kw-empty",
            memory_session_id="sess-kw-empty",

        )

        await storage.add_entries(
            entries=[entry],
            tenant_id="tenant-kw-empty",
            memory_session_id="sess-kw-empty",
            source_kind="observation",
        )

        results = await storage.keyword_search(
            keywords=["nonexistent", "keywords"],
            top_k=5,
            tenant_id="tenant-kw-empty",
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_keyword_search_tenant_isolation(
        self, storage: QdrantVectorStore
    ) -> None:
        for tenant in ["tenant-kw-iso-a", "tenant-kw-iso-b"]:
            entry = _make_entry(
                lossless_restatement="Shared keyword content about authentication",
                keywords=["auth"],
                tenant_id=tenant,
                memory_session_id=f"sess-kw-iso-{tenant}",

            )
            await storage.add_entries(
                entries=[entry],
                tenant_id=tenant,
                memory_session_id=f"sess-kw-iso-{tenant}",
                source_kind="observation",
            )

        results_a = await storage.keyword_search(
            keywords=["auth"],
            tenant_id="tenant-kw-iso-a",
        )
        results_b = await storage.keyword_search(
            keywords=["auth"],
            tenant_id="tenant-kw-iso-b",
        )

        assert all(e.tenant_id == "tenant-kw-iso-a" for e in results_a)
        assert all(e.tenant_id == "tenant-kw-iso-b" for e in results_b)

    @pytest.mark.asyncio
    async def test_structured_search_by_persons(
        self, storage: QdrantVectorStore
    ) -> None:
        entry1 = _make_entry(
            lossless_restatement="Meeting with Alice about project timeline",
            persons=["Alice", "Bob"],
            tenant_id="tenant-struct",
            memory_session_id="sess-struct-1",

        )
        entry2 = _make_entry(
            lossless_restatement="Call with Charlie about budget",
            persons=["Charlie"],
            tenant_id="tenant-struct",
            memory_session_id="sess-struct-2",

        )

        await storage.add_entries(
            entries=[entry1, entry2],
            tenant_id="tenant-struct",
            memory_session_id="sess-struct-1",
            source_kind="observation",
        )

        results = await storage.structured_search(
            persons=["Alice"],
            tenant_id="tenant-struct",
            top_k=5,
        )

        assert any("Alice" in e.persons for e in results)

    @pytest.mark.asyncio
    async def test_structured_search_by_location(
        self, storage: QdrantVectorStore
    ) -> None:
        entry1 = _make_entry(
            lossless_restatement="Meeting at Starbucks downtown",
            location="Starbucks",
            tenant_id="tenant-loc",
            memory_session_id="sess-loc-1",

        )
        entry2 = _make_entry(
            lossless_restatement="Conference at Google HQ",
            location="Google",
            tenant_id="tenant-loc",
            memory_session_id="sess-loc-2",

        )

        await storage.add_entries(
            entries=[entry1, entry2],
            tenant_id="tenant-loc",
            memory_session_id="sess-loc-1",
            source_kind="observation",
        )

        results = await storage.structured_search(
            location="Starbucks",
            tenant_id="tenant-loc",
            top_k=5,
        )

        assert len(results) >= 1
        assert any(e.location == "Starbucks" for e in results)

    @pytest.mark.asyncio
    async def test_structured_search_by_entities(
        self, storage: QdrantVectorStore
    ) -> None:
        entry1 = _make_entry(
            lossless_restatement="Integration with Stripe payment API",
            entities=["Stripe", "API"],
            tenant_id="tenant-ent",
            memory_session_id="sess-ent-1",

        )
        entry2 = _make_entry(
            lossless_restatement="AWS Lambda deployment configuration",
            entities=["AWS", "Lambda"],
            tenant_id="tenant-ent",
            memory_session_id="sess-ent-2",

        )

        await storage.add_entries(
            entries=[entry1, entry2],
            tenant_id="tenant-ent",
            memory_session_id="sess-ent-1",
            source_kind="observation",
        )

        results = await storage.structured_search(
            entities=["Stripe"],
            tenant_id="tenant-ent",
            top_k=5,
        )

        assert any("Stripe" in e.entities for e in results)

    @pytest.mark.asyncio
    async def test_structured_search_by_timestamp_range(
        self, storage: QdrantVectorStore
    ) -> None:
        entry1 = _make_entry(
            lossless_restatement="Old entry from January",
            timestamp="2025-01-15T10:00:00Z",
            tenant_id="tenant-time",
            memory_session_id="sess-time-1",

        )
        entry2 = _make_entry(
            lossless_restatement="Recent entry from March",
            timestamp="2025-03-20T15:30:00Z",
            tenant_id="tenant-time",
            memory_session_id="sess-time-2",

        )

        await storage.add_entries(
            entries=[entry1, entry2],
            tenant_id="tenant-time",
            memory_session_id="sess-time-1",
            source_kind="observation",
        )

        start_time = datetime(2025, 3, 1, tzinfo=timezone.utc)
        end_time = datetime(2025, 3, 31, tzinfo=timezone.utc)

        results = await storage.structured_search(
            timestamp_range=(start_time, end_time),
            tenant_id="tenant-time",
            top_k=5,
        )

        assert any("March" in e.lossless_restatement for e in results)

    @pytest.mark.asyncio
    async def test_structured_search_combined_filters(
        self, storage: QdrantVectorStore
    ) -> None:
        entry = _make_entry(
            lossless_restatement="Meeting with Alice at Starbucks about Stripe integration",
            persons=["Alice"],
            location="Starbucks",
            entities=["Stripe"],
            tenant_id="tenant-combined",
            memory_session_id="sess-combined",

        )

        await storage.add_entries(
            entries=[entry],
            tenant_id="tenant-combined",
            memory_session_id="sess-combined",
            source_kind="observation",
        )

        results = await storage.structured_search(
            persons=["Alice"],
            location="Starbucks",
            entities=["Stripe"],
            tenant_id="tenant-combined",
            top_k=5,
        )

        assert len(results) >= 1
        found = results[0]
        assert "Alice" in found.persons
        assert found.location == "Starbucks"
        assert "Stripe" in found.entities

    @pytest.mark.asyncio
    async def test_get_entries_for_session(
        self, storage: QdrantVectorStore
    ) -> None:
        session_id = "sess-get-001"

        for i in range(3):
            entry = _make_entry(
                lossless_restatement=f"Entry {i} for session",
                tenant_id="tenant-sess-get",
                memory_session_id=session_id,

            )
            await storage.add_entries(
                entries=[entry],
                tenant_id="tenant-sess-get",
                memory_session_id=session_id,
                source_kind="observation",
            )

        other_entry = _make_entry(
            lossless_restatement="Entry for other session",
            tenant_id="tenant-sess-get",
            memory_session_id="sess-other",

        )
        await storage.add_entries(
            entries=[other_entry],
            tenant_id="tenant-sess-get",
            memory_session_id="sess-other",
            source_kind="observation",
        )

        results = await storage.get_entries_for_session(session_id)

        assert len(results) == 3
        assert all(e.memory_session_id == session_id for e in results)

    @pytest.mark.asyncio
    async def test_get_all_entries(
        self, storage: QdrantVectorStore
    ) -> None:
        for tenant in ["tenant-all-a", "tenant-all-b"]:
            for i in range(2):
                entry = _make_entry(
                    lossless_restatement=f"Entry {i} for {tenant}",
                    tenant_id=tenant,
                    memory_session_id=f"sess-all-{tenant}",

                )
                await storage.add_entries(
                    entries=[entry],
                    tenant_id=tenant,
                    memory_session_id=f"sess-all-{tenant}",
                    source_kind="observation",
                )

        all_entries = await storage.get_all_entries()
        assert len(all_entries) == 4

        tenant_a_entries = await storage.get_all_entries(
            tenant_id="tenant-all-a"
        )
        assert len(tenant_a_entries) == 2
        assert all(e.tenant_id == "tenant-all-a" for e in tenant_a_entries)

    @pytest.mark.asyncio
    async def test_update_importance(
        self, storage: QdrantVectorStore
    ) -> None:
        entry = _make_entry(
            entry_id="entry-update-imp",
            lossless_restatement="Entry to update importance",
            tenant_id="tenant-update",
            memory_session_id="sess-update",
            importance=0.5,

        )

        await storage.add_entries(
            entries=[entry],
            tenant_id="tenant-update",
            memory_session_id="sess-update",
            source_kind="observation",
            importance=0.5,
        )

        await storage.update_importance("entry-update-imp", 0.9)

        all_entries = await storage.get_all_entries(tenant_id="tenant-update")
        found = next(e for e in all_entries if e.entry_id == "entry-update-imp")
        assert found.importance == 0.9

    @pytest.mark.asyncio
    async def test_mark_superseded(
        self, storage: QdrantVectorStore
    ) -> None:
        old_entry = _make_entry(
            entry_id="entry-old",
            lossless_restatement="Old outdated entry",
            tenant_id="tenant-super",
            memory_session_id="sess-super",

        )
        new_entry = _make_entry(
            entry_id="entry-new",
            lossless_restatement="New updated entry",
            tenant_id="tenant-super",
            memory_session_id="sess-super",

        )

        await storage.add_entries(
            entries=[old_entry, new_entry],
            tenant_id="tenant-super",
            memory_session_id="sess-super",
            source_kind="observation",
        )

        await storage.mark_superseded("entry-old", "entry-new")

        all_entries = await storage.get_all_entries(tenant_id="tenant-super")
        old_found = next(e for e in all_entries if e.entry_id == "entry-old")
        assert old_found.superseded_by == "entry-new"
        assert old_found.valid_to is not None

    @pytest.mark.asyncio
    async def test_mark_superseded_not_found(
        self, storage: QdrantVectorStore
    ) -> None:
        await storage.mark_superseded("nonexistent-entry", "new-entry")

    @pytest.mark.asyncio
    async def test_clear_all_entries(
        self, storage: QdrantVectorStore
    ) -> None:
        for i in range(3):
            entry = _make_entry(
                tenant_id="tenant-clear-all",
                memory_session_id="sess-clear-all",

            )
            await storage.add_entries(
                entries=[entry],
                tenant_id="tenant-clear-all",
                memory_session_id="sess-clear-all",
                source_kind="observation",
            )

        assert await storage.count_entries() == 3

        await storage.clear()

        count = await storage.count_entries()
        assert count == 0

    @pytest.mark.asyncio
    async def test_clear_by_tenant(
        self, storage: QdrantVectorStore
    ) -> None:
        for tenant in ["tenant-clear-one-a", "tenant-clear-one-b"]:
            entry = _make_entry(
                tenant_id=tenant,
                memory_session_id=f"sess-clear-one-{tenant}",

            )
            await storage.add_entries(
                entries=[entry],
                tenant_id=tenant,
                memory_session_id=f"sess-clear-one-{tenant}",
                source_kind="observation",
            )

        await storage.clear(tenant_id="tenant-clear-one-a")

        assert await storage.count_entries(tenant_id="tenant-clear-one-a") == 0
        assert await storage.count_entries(tenant_id="tenant-clear-one-b") == 1

    @pytest.mark.asyncio
    async def test_optimize(self, storage: QdrantVectorStore) -> None:
        entry = _make_entry(
            tenant_id="tenant-opt",
            memory_session_id="sess-opt",

        )
        await storage.add_entries(
            entries=[entry],
            tenant_id="tenant-opt",
            memory_session_id="sess-opt",
            source_kind="observation",
        )

        await storage.optimize()

    @pytest.mark.asyncio
    async def test_add_empty_entries_list(
        self, storage: QdrantVectorStore
    ) -> None:
        await storage.add_entries(
            entries=[],
            tenant_id="tenant-empty",
            memory_session_id="sess-empty",
            source_kind="observation",
        )

        assert await storage.count_entries() == 0

    @pytest.mark.asyncio
    async def test_keyword_search_empty_keywords(
        self, storage: QdrantVectorStore
    ) -> None:
        results = await storage.keyword_search(
            keywords=[],
            tenant_id="tenant-empty-kw",
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_structured_search_no_filters(
        self, storage: QdrantVectorStore
    ) -> None:
        results = await storage.structured_search(
            tenant_id="tenant-no-filters",
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_get_entries_for_nonexistent_session(
        self, storage: QdrantVectorStore
    ) -> None:
        results = await storage.get_entries_for_session("nonexistent-session")

        assert results == []

    @pytest.mark.asyncio
    async def test_update_importance_nonexistent_entry(
        self, storage: QdrantVectorStore
    ) -> None:
        await storage.update_importance("nonexistent-entry", 0.9)