# pyright: reportMissingImports=false
"""
Performance benchmark tests for critical database operations.

This module tests performance thresholds for:
1. Task queue polling - 1000 tasks, <10ms threshold
2. Audit log query - 10000 logs, 1-day range, <50ms threshold
3. Token usage aggregation - 10000 records, <100ms threshold

These benchmarks verify that the partial indexes and query optimizations
meet the required performance targets for production workloads.
"""
from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import create_engine, AsyncSession
from db.entity.task_queue_entity import TaskQueue
from db.entity.task_entity import Task
from db.entity.audit_entity import AuditLog
from db.entity.token_usage_entity import TokenUsage
from db.entity.user_entity import User
from db.entity.agent_entity import AgentInstance, AgentType
from db.types import TaskStatus, ActorType, gen_random_uuid


# =============================================================================
# Performance Thresholds
# =============================================================================
TASK_QUEUE_POLL_THRESHOLD_MS = 10.0  # <10ms for 1000 tasks
AUDIT_LOG_QUERY_THRESHOLD_MS = 50.0  # <50ms for 10000 logs, 1-day range
TOKEN_AGGREGATION_THRESHOLD_MS = 100.0  # <100ms for 10000 records

# Data sizes for benchmarks
TASK_QUEUE_DATA_SIZE = 1000
AUDIT_LOG_DATA_SIZE = 10000
TOKEN_USAGE_DATA_SIZE = 10000


@pytest_asyncio.fixture(scope="module")
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session for performance benchmarks.
    
    Uses module scope to avoid recreating tables for each test.
    """
    dsn = (
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'agentserver')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'testpass')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'agentserver')}"
    )
    
    engine = create_engine(dsn=dsn)
    async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    # Create all required tables
    async with engine.begin() as conn:
        # Users table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Agent types table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_types (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                capabilities JSONB,
                default_config JSONB,
                is_active BOOLEAN NOT NULL DEFAULT true,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Agent instances table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS agent_instances (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                agent_type_id UUID NOT NULL REFERENCES agent_types(id) ON DELETE CASCADE,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name TEXT,
                status TEXT NOT NULL DEFAULT 'idle' 
                    CHECK (status IN ('idle', 'busy', 'error', 'offline')),
                config JSONB,
                last_heartbeat_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Tasks table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS tasks (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                agent_id UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
                session_id TEXT,
                parent_task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
                priority TEXT NOT NULL DEFAULT 'normal'
                    CHECK (priority IN ('low', 'normal', 'high', 'critical')),
                payload JSONB,
                result JSONB,
                error_message TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                scheduled_at TIMESTAMPTZ,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        
        # Task queue table with partial indexes
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS task_queue (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
                priority INTEGER NOT NULL DEFAULT 0,
                queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                scheduled_at TIMESTAMPTZ,
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                claimed_by UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
                claimed_at TIMESTAMPTZ,
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retries INTEGER NOT NULL DEFAULT 3,
                error_message TEXT,
                result_json JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ck_task_queue_retry_count CHECK (retry_count >= 0),
                CONSTRAINT ck_task_queue_max_retries CHECK (max_retries >= 0),
                CONSTRAINT ck_task_queue_priority CHECK (priority >= 0)
            )
        """))
        
        # Create task_queue indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_task_queue_task_id ON task_queue(task_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_task_queue_claimed_by ON task_queue(claimed_by)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_queue_poll
            ON task_queue(priority DESC, scheduled_at ASC)
            WHERE status = 'pending'
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_queue_claimed
            ON task_queue(claimed_by)
            WHERE status = 'running'
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_queue_retry
            ON task_queue(retry_count)
            WHERE status = 'pending'
        """))
        
        # Tasks indexes
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, created_at)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id, created_at)
        """))
        
        # Audit schema and table
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS audit"))
        await conn.execute(text("""
            DO $$ BEGIN
                CREATE TYPE audit.actor_type_enum AS ENUM ('user', 'agent', 'system');
            EXCEPTION
                WHEN duplicate_object THEN null;
            END $$;
        """))
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS audit.audit_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID,
                actor_type audit.actor_type_enum NOT NULL,
                actor_id UUID NOT NULL,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id UUID NOT NULL,
                old_values JSONB,
                new_values JSONB,
                ip_address INET,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_audit_user_time 
            ON audit.audit_log(user_id, created_at DESC)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_audit_resource 
            ON audit.audit_log(resource_type, resource_id)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_audit_created_at 
            ON audit.audit_log(created_at DESC)
        """))
        
        # Token usage table
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                agent_id UUID NOT NULL REFERENCES agent_instances(id) ON DELETE CASCADE,
                session_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                estimated_cost_usd NUMERIC(10, 6) NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_user_created 
            ON token_usage(user_id, created_at)
        """))
        await conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_token_usage_session 
            ON token_usage(session_id)
        """))
    
    async with async_session_factory() as session:
        yield session
    
    # Cleanup
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS token_usage CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS audit.audit_log"))
        await conn.execute(text("DROP TYPE IF EXISTS audit.actor_type_enum"))
        await conn.execute(text("DROP SCHEMA IF EXISTS audit"))
        await conn.execute(text("DROP TABLE IF EXISTS task_queue CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS tasks CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_instances CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS agent_types CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS users CASCADE"))
    
    await engine.dispose()


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession) -> User:
    """Create a sample user for testing."""
    user = User(
        username=f"bench_user_{uuid4().hex[:8]}",
        email=f"bench_{uuid4().hex[:8]}@example.com",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def sample_agent_type(db_session: AsyncSession) -> AgentType:
    """Create a sample agent type for testing."""
    agent_type = AgentType(
        name=f"bench_agent_type_{uuid4().hex[:8]}",
        description="Benchmark agent type",
        is_active=True,
    )
    db_session.add(agent_type)
    await db_session.commit()
    await db_session.refresh(agent_type)
    return agent_type


@pytest_asyncio.fixture
async def sample_agent_instance(
    db_session: AsyncSession,
    sample_user: User,
    sample_agent_type: AgentType,
) -> AgentInstance:
    """Create a sample agent instance for testing."""
    agent = AgentInstance(
        agent_type_id=sample_agent_type.id,
        user_id=sample_user.id,
        name="Benchmark Agent",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


class TestTaskQueuePollingPerformance:
    """Benchmark tests for task queue polling performance.
    
    Target: <10ms for querying 1000 pending tasks with priority ordering.
    """
    
    @pytest_asyncio.fixture
    async def populated_queue(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ) -> int:
        """Populate the task queue with benchmark data."""
        # Clear existing data
        await db_session.execute(text("DELETE FROM task_queue"))
        await db_session.execute(text("DELETE FROM tasks"))
        await db_session.commit()
        
        user_id = sample_user.id
        tasks_data = []
        queue_data = []
        
        # Create tasks and queue entries in batches
        batch_size = 100
        now = datetime.now(timezone.utc)
        
        for batch_start in range(0, TASK_QUEUE_DATA_SIZE, batch_size):
            batch_end = min(batch_start + batch_size, TASK_QUEUE_DATA_SIZE)
            
            for i in range(batch_start, batch_end):
                task_id = uuid4()
                tasks_data.append({
                    "id": task_id,
                    "user_id": user_id,
                    "task_type": f"benchmark_task_{i}",
                    "status": "pending",
                    "priority": "normal",
                })
                
                # Vary priority and scheduled_at for realistic distribution
                priority = i % 10  # Priorities 0-9
                scheduled_at = now + timedelta(hours=i % 24) if i % 3 == 0 else None
                
                queue_data.append({
                    "id": uuid4(),
                    "task_id": task_id,
                    "status": "pending",
                    "priority": priority,
                    "scheduled_at": scheduled_at,
                    "queued_at": now,
                })
        
        # Insert in batches
        for i in range(0, len(tasks_data), batch_size):
            batch = tasks_data[i:i + batch_size]
            values = ", ".join([
                f"('{t['id']}', '{t['user_id']}', '{t['task_type']}', '{t['status']}', '{t['priority']}')"
                for t in batch
            ])
            await db_session.execute(text(f"""
                INSERT INTO tasks (id, user_id, task_type, status, priority)
                VALUES {values}
            """))
        
        for i in range(0, len(queue_data), batch_size):
            batch = queue_data[i:i + batch_size]
            values = ", ".join([
                f"('{q['id']}', '{q['task_id']}', '{q['status']}', {q['priority']}, "
                f"{f"'{q['scheduled_at'].isoformat()}'" if q['scheduled_at'] else 'NULL'}, "
                f"'{q['queued_at'].isoformat()}')"
                for q in batch
            ])
            await db_session.execute(text(f"""
                INSERT INTO task_queue (id, task_id, status, priority, scheduled_at, queued_at)
                VALUES {values}
            """))
        
        await db_session.commit()
        return len(queue_data)
    
    async def test_queue_poll_performance(
        self,
        db_session: AsyncSession,
        populated_queue: int,
    ):
        """Test that queue polling completes within <10ms threshold."""
        # Warm-up query (to populate any caches)
        await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.pending)
            .order_by(TaskQueue.priority.desc(), TaskQueue.scheduled_at.asc().nulls_first())
            .limit(10)
        )
        await db_session.commit()
        
        # Measure query performance
        start_time = time.perf_counter()
        
        result = await db_session.execute(
            select(TaskQueue)
            .where(TaskQueue.status == TaskStatus.pending)
            .order_by(TaskQueue.priority.desc(), TaskQueue.scheduled_at.asc().nulls_first())
            .limit(100)  # Typical batch size for polling
        )
        entries = result.scalars().all()
        
        end_time = time.perf_counter()
        elapsed_ms = (end_time - start_time) * 1000
        
        # Verify results
        assert len(entries) == 100, f"Expected 100 entries, got {len(entries)}"
        
        # Verify ordering (highest priority first)
        priorities = [e.priority for e in entries]
        assert priorities == sorted(priorities, reverse=True), "Entries not ordered by priority DESC"
        
        # Check performance threshold
        print(f"\n  Task Queue Poll: {elapsed_ms:.2f}ms (threshold: {TASK_QUEUE_POLL_THRESHOLD_MS}ms)")
        
        assert elapsed_ms < TASK_QUEUE_POLL_THRESHOLD_MS, (
            f"Queue polling took {elapsed_ms:.2f}ms, exceeding threshold of {TASK_QUEUE_POLL_THRESHOLD_MS}ms"
        )


class TestAuditLogQueryPerformance:
    """Benchmark tests for audit log query performance.
    
    Target: <50ms for querying 10000 audit logs within a 1-day range.
    """
    
    @pytest_asyncio.fixture
    async def populated_audit_logs(
        self,
        db_session: AsyncSession,
        sample_user: User,
    ) -> int:
        """Populate audit logs with benchmark data."""
        # Clear existing data
        await db_session.execute(text("DELETE FROM audit.audit_log"))
        await db_session.commit()
        
        user_id = sample_user.id
        logs_data = []
        
        now = datetime.now(timezone.utc)
        batch_size = 500
        
        # Create logs spanning multiple days
        for i in range(AUDIT_LOG_DATA_SIZE):
            # Distribute logs across 7 days
            days_ago = i % 7
            hours_offset = (i * 5) % 24
            created_at = now - timedelta(days=days_ago, hours=hours_offset)
            
            logs_data.append({
                "id": uuid4(),
                "user_id": user_id,
                "actor_type": "user",
                "actor_id": user_id,
                "action": ["create", "update", "delete", "read"][i % 4],
                "resource_type": ["task", "user", "agent", "session"][i % 4],
                "resource_id": uuid4(),
                "created_at": created_at.isoformat(),
            })
        
        # Insert in batches
        for i in range(0, len(logs_data), batch_size):
            batch = logs_data[i:i + batch_size]
            values = ", ".join([
                f"('{l['id']}', '{l['user_id']}', '{l['actor_type']}', '{l['actor_id']}', "
                f"'{l['action']}', '{l['resource_type']}', '{l['resource_id']}', "
                f"'{l['created_at']}')"
                for l in batch
            ])
            await db_session.execute(text(f"""
                INSERT INTO audit.audit_log 
                (id, user_id, actor_type, actor_id, action, resource_type, resource_id, created_at)
                VALUES {values}
            """))
        
        await db_session.commit()
        return len(logs_data)
    
    async def test_audit_log_query_performance(
        self,
        db_session: AsyncSession,
        populated_audit_logs: int,
    ):
        """Test that 1-day audit log query completes within <50ms threshold."""
        now = datetime.now(timezone.utc)
        one_day_ago = now - timedelta(days=1)
        
        # Warm-up query
        await db_session.execute(
            select(AuditLog)
            .where(AuditLog.created_at >= one_day_ago)
            .limit(10)
        )
        await db_session.commit()
        
        # Measure query performance for 1-day range
        start_time = time.perf_counter()
        
        result = await db_session.execute(
            select(AuditLog)
            .where(AuditLog.created_at >= one_day_ago)
            .order_by(AuditLog.created_at.desc())
            .limit(1000)  # Typical page size
        )
        entries = result.scalars().all()
        
        end_time = time.perf_counter()
        elapsed_ms = (end_time - start_time) * 1000
        
        # Verify we got results from the last day
        assert len(entries) > 0, "Expected some audit log entries"
        
        # Verify ordering (newest first)
        timestamps = [e.created_at for e in entries]
        assert timestamps == sorted(timestamps, reverse=True), "Entries not ordered by created_at DESC"
        
        # Check performance threshold
        print(f"\n  Audit Log Query (1-day): {elapsed_ms:.2f}ms (threshold: {AUDIT_LOG_QUERY_THRESHOLD_MS}ms)")
        
        assert elapsed_ms < AUDIT_LOG_QUERY_THRESHOLD_MS, (
            f"Audit log query took {elapsed_ms:.2f}ms, exceeding threshold of {AUDIT_LOG_QUERY_THRESHOLD_MS}ms"
        )


class TestTokenUsageAggregationPerformance:
    """Benchmark tests for token usage aggregation performance.
    
    Target: <100ms for aggregating 10000 token usage records.
    """
    
    @pytest_asyncio.fixture
    async def populated_token_usage(
        self,
        db_session: AsyncSession,
        sample_user: User,
        sample_agent_instance: AgentInstance,
    ) -> int:
        """Populate token usage with benchmark data."""
        # Clear existing data
        await db_session.execute(text("DELETE FROM token_usage"))
        await db_session.commit()
        
        user_id = sample_user.id
        agent_id = sample_agent_instance.id
        usage_data = []
        
        now = datetime.now(timezone.utc)
        batch_size = 500
        
        # Create varied token usage records
        for i in range(TOKEN_USAGE_DATA_SIZE):
            # Vary sessions and models
            session_id = f"session_{i % 100}"  # 100 different sessions
            model_name = ["gpt-4", "gpt-3.5-turbo", "claude-3", "claude-2"][i % 4]
            
            # Vary token counts
            input_tokens = 100 + (i % 500) * 10
            output_tokens = 50 + (i % 200) * 5
            total_tokens = input_tokens + output_tokens
            cost = Decimal(str(total_tokens * 0.00001))
            
            # Distribute across time
            hours_offset = i % 168  # Across a week
            created_at = now - timedelta(hours=hours_offset)
            
            usage_data.append({
                "id": uuid4(),
                "user_id": user_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "model_name": model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "estimated_cost_usd": str(cost),
                "created_at": created_at.isoformat(),
            })
        
        # Insert in batches
        for i in range(0, len(usage_data), batch_size):
            batch = usage_data[i:i + batch_size]
            values = ", ".join([
                f"('{u['id']}', '{u['user_id']}', '{u['agent_id']}', '{u['session_id']}', "
                f"'{u['model_name']}', {u['input_tokens']}, {u['output_tokens']}, "
                f"{u['total_tokens']}, {u['estimated_cost_usd']}, '{u['created_at']}')"
                for u in batch
            ])
            await db_session.execute(text(f"""
                INSERT INTO token_usage 
                (id, user_id, agent_id, session_id, model_name, 
                 input_tokens, output_tokens, total_tokens, estimated_cost_usd, created_at)
                VALUES {values}
            """))
        
        await db_session.commit()
        return len(usage_data)
    
    async def test_token_aggregation_performance(
        self,
        db_session: AsyncSession,
        populated_token_usage: int,
    ):
        """Test that token usage aggregation completes within <100ms threshold."""
        # Warm-up query
        await db_session.execute(
            select(func.sum(TokenUsage.total_tokens))
        )
        await db_session.commit()
        
        # Measure aggregation performance
        # Common aggregation: total tokens and cost by model
        start_time = time.perf_counter()
        
        result = await db_session.execute(
            select(
                TokenUsage.model_name,
                func.count(TokenUsage.id).label("request_count"),
                func.sum(TokenUsage.input_tokens).label("total_input_tokens"),
                func.sum(TokenUsage.output_tokens).label("total_output_tokens"),
                func.sum(TokenUsage.total_tokens).label("total_tokens"),
                func.sum(TokenUsage.estimated_cost_usd).label("total_cost"),
            )
            .group_by(TokenUsage.model_name)
            .order_by(func.sum(TokenUsage.total_tokens).desc())
        )
        aggregates = result.all()
        
        end_time = time.perf_counter()
        elapsed_ms = (end_time - start_time) * 1000
        
        # Verify results
        assert len(aggregates) == 4, f"Expected 4 model groups, got {len(aggregates)}"
        
        # Verify totals
        total_tokens = sum(a.total_tokens for a in aggregates)
        assert total_tokens > 0, "Expected some total tokens"
        
        # Check performance threshold
        print(f"\n  Token Usage Aggregation: {elapsed_ms:.2f}ms (threshold: {TOKEN_AGGREGATION_THRESHOLD_MS}ms)")
        
        assert elapsed_ms < TOKEN_AGGREGATION_THRESHOLD_MS, (
            f"Token aggregation took {elapsed_ms:.2f}ms, exceeding threshold of {TOKEN_AGGREGATION_THRESHOLD_MS}ms"
        )
    
    async def test_session_aggregation_performance(
        self,
        db_session: AsyncSession,
        populated_token_usage: int,
    ):
        """Test that session-level aggregation completes within <100ms threshold."""
        # Measure session aggregation performance
        start_time = time.perf_counter()
        
        result = await db_session.execute(
            select(
                TokenUsage.session_id,
                func.count(TokenUsage.id).label("request_count"),
                func.sum(TokenUsage.total_tokens).label("total_tokens"),
                func.sum(TokenUsage.estimated_cost_usd).label("total_cost"),
                func.min(TokenUsage.created_at).label("first_request"),
                func.max(TokenUsage.created_at).label("last_request"),
            )
            .group_by(TokenUsage.session_id)
            .order_by(func.sum(TokenUsage.total_tokens).desc())
            .limit(50)
        )
        session_aggregates = result.all()
        
        end_time = time.perf_counter()
        elapsed_ms = (end_time - start_time) * 1000
        
        # Verify results
        assert len(session_aggregates) == 50, f"Expected 50 session groups, got {len(session_aggregates)}"
        
        # Check performance threshold
        print(f"\n  Session Aggregation: {elapsed_ms:.2f}ms (threshold: {TOKEN_AGGREGATION_THRESHOLD_MS}ms)")
        
        assert elapsed_ms < TOKEN_AGGREGATION_THRESHOLD_MS, (
            f"Session aggregation took {elapsed_ms:.2f}ms, exceeding threshold of {TOKEN_AGGREGATION_THRESHOLD_MS}ms"
        )


class TestBenchmarkReport:
    """Generate consolidated benchmark report."""
    
    def test_performance_thresholds_defined(self):
        """Verify all performance thresholds are defined."""
        assert TASK_QUEUE_POLL_THRESHOLD_MS == 10.0
        assert AUDIT_LOG_QUERY_THRESHOLD_MS == 50.0
        assert TOKEN_AGGREGATION_THRESHOLD_MS == 100.0
        
        print("\n" + "=" * 60)
        print("PERFORMANCE BENCHMARK THRESHOLDS")
        print("=" * 60)
        print(f"  Task Queue Polling:    <{TASK_QUEUE_POLL_THRESHOLD_MS}ms (for {TASK_QUEUE_DATA_SIZE} tasks)")
        print(f"  Audit Log Query:       <{AUDIT_LOG_QUERY_THRESHOLD_MS}ms (for {AUDIT_LOG_DATA_SIZE} logs, 1-day range)")
        print(f"  Token Aggregation:     <{TOKEN_AGGREGATION_THRESHOLD_MS}ms (for {TOKEN_USAGE_DATA_SIZE} records)")
        print("=" * 60)