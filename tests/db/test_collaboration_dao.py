# pyright: reportMissingImports=false
"""
Tests for CollaborationSessionDAO and AgentMessageDAO database operations.

This module tests CRUD operations for collaboration sessions and agent messages
following the DAO pattern with the new entity/dto/dao architecture.

Import path: db.dao.collaboration_session_dao, db.dao.agent_message_dao
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from dotenv import load_dotenv
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Load environment variables from .env file
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from db import create_engine, AsyncSession as DBAsyncSession
from db.dto.collaboration_dto import (
    CollaborationSessionCreate,
    CollaborationSession,
    CollaborationSessionUpdate,
    AgentMessageCreate,
    AgentMessage,
    AgentMessageUpdate,
)
from db.dao.collaboration_session_dao import CollaborationSessionDAO
from db.dao.agent_message_dao import AgentMessageDAO
from db.entity.collaboration_entity import (
    CollaborationSession as CollaborationSessionEntity,
    AgentMessage as AgentMessageEntity,
)
from db.entity.user_entity import User as UserEntity
from db.entity.agent_entity import AgentType, AgentInstance
from db.entity.llm_endpoint_entity import LLMEndpoint, LLMEndpointGroup  # Required for UserEntity relationships


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[DBAsyncSession, None]:
    """Create a test database session.
    
    This fixture creates a new engine and session for each test,
    ensuring test isolation by cleaning data rather than dropping tables.
    """
    dsn = (
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'agentserver')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'testpass')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'agentserver')}"
    )
    
    engine = create_engine(dsn=dsn)
    async_session = async_sessionmaker(engine, class_=DBAsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        yield session
        await session.rollback()
    
    await engine.dispose()


@pytest_asyncio.fixture
async def clean_data(db_session: DBAsyncSession) -> AsyncGenerator[None, None]:
    """Clean all collaboration-related tables before and after tests."""
    # Clean before test
    await db_session.execute(delete(AgentMessageEntity))
    await db_session.execute(delete(CollaborationSessionEntity))
    await db_session.execute(delete(AgentInstance))
    await db_session.execute(delete(AgentType))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()
    
    yield
    
    # Clean after test
    await db_session.rollback()
    await db_session.execute(delete(AgentMessageEntity))
    await db_session.execute(delete(CollaborationSessionEntity))
    await db_session.execute(delete(AgentInstance))
    await db_session.execute(delete(AgentType))
    await db_session.execute(delete(UserEntity))
    await db_session.commit()


@pytest_asyncio.fixture
async def test_user(db_session: DBAsyncSession, clean_data: None) -> UserEntity:
    """Create a test user for collaboration ownership."""
    user = UserEntity(
        username="collabtestuser",
        email="collabtest@example.com",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_agent_type(db_session: DBAsyncSession, test_user: UserEntity) -> AgentType:
    """Create a test agent type."""
    agent_type = AgentType(
        name="CollabTestAgent",
    )
    db_session.add(agent_type)
    await db_session.commit()
    await db_session.refresh(agent_type)
    return agent_type


@pytest_asyncio.fixture
async def test_agent_instance(
    db_session: DBAsyncSession,
    test_user: UserEntity,
    test_agent_type: AgentType,
) -> AgentInstance:
    """Create a test agent instance."""
    agent = AgentInstance(
        agent_type_id=test_agent_type.id,
        user_id=test_user.id,
        status="idle",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


# =============================================================================
# CollaborationSession DAO CRUD Tests
# =============================================================================

class TestCollaborationSessionDAOCreate:
    """Tests for CollaborationSessionDAO.create method."""
    
    async def test_create_minimal(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test creating a collaboration session with minimal required fields."""
        dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
        )
        
        result = await CollaborationSessionDAO.create(dto, session=db_session)
        
        assert result.id is not None
        assert result.user_id == test_user.id
        assert result.main_agent_id == test_agent_instance.id
        assert result.status == "active"
        assert result.involves_secrets is False
        assert result.created_at is not None
        assert result.updated_at is not None
    
    async def test_create_with_all_fields(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test creating a collaboration session with all fields."""
        dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
            name="Test Collaboration",
            status="active",
            involves_secrets=True,
            context_json={"topic": "research", "agents": 3},
        )
        
        result = await CollaborationSessionDAO.create(dto, session=db_session)
        
        assert result.name == "Test Collaboration"
        assert result.involves_secrets is True
        assert result.context_json == {"topic": "research", "agents": 3}
    
    async def test_create_without_session_param(
        self,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test creating a collaboration session without passing session."""
        dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
        )
        
        result = await CollaborationSessionDAO.create(dto)
        
        assert result.id is not None
        assert result.user_id == test_user.id
        
        # Cleanup
        await CollaborationSessionDAO.delete(result.id)


class TestCollaborationSessionDAOGetById:
    """Tests for CollaborationSessionDAO.get_by_id method."""
    
    async def test_get_by_id_exists(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test retrieving an existing collaboration session."""
        create_dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
            name="Test Session",
        )
        created = await CollaborationSessionDAO.create(create_dto, session=db_session)
        
        result = await CollaborationSessionDAO.get_by_id(created.id, session=db_session)
        
        assert result is not None
        assert result.id == created.id
        assert result.name == "Test Session"
    
    async def test_get_by_id_not_found(self, db_session: DBAsyncSession):
        """Test retrieving a non-existent collaboration session."""
        result = await CollaborationSessionDAO.get_by_id(uuid4(), session=db_session)
        
        assert result is None
    
    async def test_get_by_id_without_session_param(
        self,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test retrieving a session without passing session parameter."""
        create_dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
        )
        created = await CollaborationSessionDAO.create(create_dto)
        
        result = await CollaborationSessionDAO.get_by_id(created.id)
        
        assert result is not None
        assert result.id == created.id
        
        # Cleanup
        await CollaborationSessionDAO.delete(created.id)


class TestCollaborationSessionDAOGetByUserId:
    """Tests for CollaborationSessionDAO.get_by_user_id method."""
    
    async def test_get_by_user_id_returns_sessions(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test retrieving sessions by user ID."""
        for i in range(3):
            dto = CollaborationSessionCreate(
                user_id=test_user.id,
                main_agent_id=test_agent_instance.id,
                session_id=f"session-{uuid4()}",
                name=f"Session {i}",
            )
            await CollaborationSessionDAO.create(dto, session=db_session)
        
        results = await CollaborationSessionDAO.get_by_user_id(
            test_user.id, session=db_session
        )
        
        assert len(results) == 3
    
    async def test_get_by_user_id_no_sessions(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
    ):
        """Test retrieving sessions for user with no sessions."""
        results = await CollaborationSessionDAO.get_by_user_id(
            test_user.id, session=db_session
        )
        
        assert len(results) == 0
    
    async def test_get_by_user_id_with_pagination(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test retrieving sessions with pagination."""
        for i in range(5):
            dto = CollaborationSessionCreate(
                user_id=test_user.id,
                main_agent_id=test_agent_instance.id,
                session_id=f"session-{uuid4()}",
            )
            await CollaborationSessionDAO.create(dto, session=db_session)
        
        page1 = await CollaborationSessionDAO.get_by_user_id(
            test_user.id, limit=2, offset=0, session=db_session
        )
        page2 = await CollaborationSessionDAO.get_by_user_id(
            test_user.id, limit=2, offset=2, session=db_session
        )
        
        assert len(page1) == 2
        assert len(page2) == 2


class TestCollaborationSessionDAOGetBySessionId:
    """Tests for CollaborationSessionDAO.get_by_session_id method."""
    
    async def test_get_by_session_id_exists(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test retrieving a session by unique session_id."""
        session_id = f"session-{uuid4()}"
        create_dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=session_id,
        )
        await CollaborationSessionDAO.create(create_dto, session=db_session)
        
        result = await CollaborationSessionDAO.get_by_session_id(
            session_id, session=db_session
        )
        
        assert result is not None
        assert result.session_id == session_id
    
    async def test_get_by_session_id_not_found(self, db_session: DBAsyncSession):
        """Test retrieving a session by non-existent session_id."""
        result = await CollaborationSessionDAO.get_by_session_id(
            "nonexistent-session", session=db_session
        )
        
        assert result is None


class TestCollaborationSessionDAOGetAll:
    """Tests for CollaborationSessionDAO.get_all method."""
    
    async def test_get_all_returns_all(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test retrieving all collaboration sessions."""
        for i in range(3):
            dto = CollaborationSessionCreate(
                user_id=test_user.id,
                main_agent_id=test_agent_instance.id,
                session_id=f"session-{uuid4()}",
            )
            await CollaborationSessionDAO.create(dto, session=db_session)
        
        results = await CollaborationSessionDAO.get_all(session=db_session)
        
        assert len(results) >= 3
    
    async def test_get_all_with_status_filter(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test retrieving sessions filtered by status."""
        # Create sessions with different statuses
        dto1 = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
            status="active",
        )
        await CollaborationSessionDAO.create(dto1, session=db_session)
        
        dto2 = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
            status="completed",
        )
        await CollaborationSessionDAO.create(dto2, session=db_session)
        
        active = await CollaborationSessionDAO.get_all(
            status="active", session=db_session
        )
        
        assert all(s.status == "active" for s in active)
    
    async def test_get_all_with_pagination(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test retrieving sessions with pagination."""
        for i in range(5):
            dto = CollaborationSessionCreate(
                user_id=test_user.id,
                main_agent_id=test_agent_instance.id,
                session_id=f"session-{uuid4()}",
            )
            await CollaborationSessionDAO.create(dto, session=db_session)
        
        page1 = await CollaborationSessionDAO.get_all(
            limit=2, offset=0, session=db_session
        )
        
        assert len(page1) == 2


class TestCollaborationSessionDAOUpdate:
    """Tests for CollaborationSessionDAO.update method."""
    
    async def test_update_status(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test updating session status."""
        create_dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
        )
        created = await CollaborationSessionDAO.create(create_dto, session=db_session)
        
        update_dto = CollaborationSessionUpdate(
            id=created.id,
            status="completed",
        )
        result = await CollaborationSessionDAO.update(update_dto, session=db_session)
        
        assert result is not None
        assert result.status == "completed"
    
    async def test_update_name(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test updating session name."""
        create_dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
        )
        created = await CollaborationSessionDAO.create(create_dto, session=db_session)
        
        update_dto = CollaborationSessionUpdate(
            id=created.id,
            name="Updated Name",
        )
        result = await CollaborationSessionDAO.update(update_dto, session=db_session)
        
        assert result is not None
        assert result.name == "Updated Name"
    
    async def test_update_context_json(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test updating session context_json."""
        create_dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
        )
        created = await CollaborationSessionDAO.create(create_dto, session=db_session)
        
        update_dto = CollaborationSessionUpdate(
            id=created.id,
            context_json={"new": "context"},
        )
        result = await CollaborationSessionDAO.update(update_dto, session=db_session)
        
        assert result is not None
        assert result.context_json == {"new": "context"}
    
    async def test_update_ended_at(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test updating session ended_at timestamp."""
        create_dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
        )
        created = await CollaborationSessionDAO.create(create_dto, session=db_session)
        
        ended_at = datetime.now(timezone.utc)
        update_dto = CollaborationSessionUpdate(
            id=created.id,
            ended_at=ended_at,
        )
        result = await CollaborationSessionDAO.update(update_dto, session=db_session)
        
        assert result is not None
        assert result.ended_at is not None
    
    async def test_update_nonexistent_returns_none(self, db_session: DBAsyncSession):
        """Test updating a non-existent session returns None."""
        update_dto = CollaborationSessionUpdate(
            id=uuid4(),
            name="Updated",
        )
        result = await CollaborationSessionDAO.update(update_dto, session=db_session)
        
        assert result is None


class TestCollaborationSessionDAODelete:
    """Tests for CollaborationSessionDAO.delete method."""
    
    async def test_delete_existing(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test deleting an existing session."""
        create_dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
        )
        created = await CollaborationSessionDAO.create(create_dto, session=db_session)
        
        success = await CollaborationSessionDAO.delete(created.id, session=db_session)
        
        assert success is True
        
        result = await CollaborationSessionDAO.get_by_id(created.id, session=db_session)
        assert result is None
    
    async def test_delete_nonexistent_returns_false(self, db_session: DBAsyncSession):
        """Test deleting a non-existent session returns False."""
        success = await CollaborationSessionDAO.delete(uuid4(), session=db_session)
        
        assert success is False


class TestCollaborationSessionDAOExists:
    """Tests for CollaborationSessionDAO.exists method."""
    
    async def test_exists_true(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test exists returns True for existing session."""
        create_dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
        )
        created = await CollaborationSessionDAO.create(create_dto, session=db_session)
        
        exists = await CollaborationSessionDAO.exists(created.id, session=db_session)
        
        assert exists is True
    
    async def test_exists_false(self, db_session: DBAsyncSession):
        """Test exists returns False for non-existent session."""
        exists = await CollaborationSessionDAO.exists(uuid4(), session=db_session)
        
        assert exists is False


class TestCollaborationSessionDAOCount:
    """Tests for CollaborationSessionDAO.count method."""
    
    async def test_count_returns_correct_number(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test count returns correct number of sessions."""
        initial_count = await CollaborationSessionDAO.count(session=db_session)
        
        for i in range(3):
            dto = CollaborationSessionCreate(
                user_id=test_user.id,
                main_agent_id=test_agent_instance.id,
                session_id=f"session-{uuid4()}",
            )
            await CollaborationSessionDAO.create(dto, session=db_session)
        
        final_count = await CollaborationSessionDAO.count(session=db_session)
        
        assert final_count == initial_count + 3


# =============================================================================
# AgentMessage DAO CRUD Tests
# =============================================================================

@pytest_asyncio.fixture
async def test_collaboration_session(
    db_session: DBAsyncSession,
    test_user: UserEntity,
    test_agent_instance: AgentInstance,
) -> CollaborationSession:
    """Create a test collaboration session for message tests."""
    dto = CollaborationSessionCreate(
        user_id=test_user.id,
        main_agent_id=test_agent_instance.id,
        session_id=f"session-{uuid4()}",
        name="Test Collaboration",
    )
    return await CollaborationSessionDAO.create(dto, session=db_session)


class TestAgentMessageDAOCreate:
    """Tests for AgentMessageDAO.create method."""
    
    async def test_create_minimal(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test creating an agent message with minimal required fields."""
        dto = AgentMessageCreate(
            collaboration_id=test_collaboration_session.id,
            content_json={"action": "test"},
        )
        
        result = await AgentMessageDAO.create(dto, session=db_session)
        
        assert result.id is not None
        assert result.collaboration_id == test_collaboration_session.id
        assert result.message_type == "request"
        assert result.redaction_level == "none"
        assert result.content_json == {"action": "test"}
        assert result.created_at is not None
    
    async def test_create_with_all_fields(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
        test_agent_instance: AgentInstance,
    ):
        """Test creating an agent message with all fields."""
        dto = AgentMessageCreate(
            collaboration_id=test_collaboration_session.id,
            step_id="step-001",
            sender_agent_id=test_agent_instance.id,
            receiver_agent_id=test_agent_instance.id,
            message_type="tool_call",
            content_json={"tool": "search", "query": "test"},
            redaction_level="partial",
        )
        
        result = await AgentMessageDAO.create(dto, session=db_session)
        
        assert result.step_id == "step-001"
        assert result.sender_agent_id == test_agent_instance.id
        assert result.receiver_agent_id == test_agent_instance.id
        assert result.message_type == "tool_call"
        assert result.redaction_level == "partial"
    
    async def test_create_without_session_param(
        self,
        test_collaboration_session: CollaborationSession,
    ):
        """Test creating an agent message without passing session."""
        dto = AgentMessageCreate(
            collaboration_id=test_collaboration_session.id,
            content_json={"action": "test"},
        )
        
        result = await AgentMessageDAO.create(dto)
        
        assert result.id is not None
        
        # Cleanup
        await AgentMessageDAO.delete(result.id)


class TestAgentMessageDAOGetById:
    """Tests for AgentMessageDAO.get_by_id method."""
    
    async def test_get_by_id_exists(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test retrieving an existing agent message."""
        create_dto = AgentMessageCreate(
            collaboration_id=test_collaboration_session.id,
            content_json={"test": "data"},
        )
        created = await AgentMessageDAO.create(create_dto, session=db_session)
        
        result = await AgentMessageDAO.get_by_id(created.id, session=db_session)
        
        assert result is not None
        assert result.id == created.id
    
    async def test_get_by_id_not_found(self, db_session: DBAsyncSession):
        """Test retrieving a non-existent agent message."""
        result = await AgentMessageDAO.get_by_id(uuid4(), session=db_session)
        
        assert result is None


class TestAgentMessageDAOGetByCollaborationId:
    """Tests for AgentMessageDAO.get_by_collaboration_id method."""
    
    async def test_get_by_collaboration_id_returns_messages(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test retrieving messages by collaboration_id."""
        for i in range(3):
            dto = AgentMessageCreate(
                collaboration_id=test_collaboration_session.id,
                content_json={"index": i},
            )
            await AgentMessageDAO.create(dto, session=db_session)
        
        results = await AgentMessageDAO.get_by_collaboration_id(
            test_collaboration_session.id, session=db_session
        )
        
        assert len(results) == 3
    
    async def test_get_by_collaboration_id_no_messages(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test retrieving messages for collaboration with no messages."""
        results = await AgentMessageDAO.get_by_collaboration_id(
            test_collaboration_session.id, session=db_session
        )
        
        assert len(results) == 0
    
    async def test_get_by_collaboration_id_with_pagination(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test retrieving messages with pagination."""
        for i in range(5):
            dto = AgentMessageCreate(
                collaboration_id=test_collaboration_session.id,
                content_json={"index": i},
            )
            await AgentMessageDAO.create(dto, session=db_session)
        
        page1 = await AgentMessageDAO.get_by_collaboration_id(
            test_collaboration_session.id, limit=2, offset=0, session=db_session
        )
        
        assert len(page1) == 2


class TestAgentMessageDAOGetByStepId:
    """Tests for AgentMessageDAO.get_by_step_id method."""
    
    async def test_get_by_step_id_returns_messages(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test retrieving messages by step_id."""
        step_id = "step-test-001"
        for i in range(2):
            dto = AgentMessageCreate(
                collaboration_id=test_collaboration_session.id,
                step_id=step_id,
                content_json={"index": i},
            )
            await AgentMessageDAO.create(dto, session=db_session)
        
        # Create a message with different step_id
        other_dto = AgentMessageCreate(
            collaboration_id=test_collaboration_session.id,
            step_id="other-step",
            content_json={"other": True},
        )
        await AgentMessageDAO.create(other_dto, session=db_session)
        
        results = await AgentMessageDAO.get_by_step_id(step_id, session=db_session)
        
        assert len(results) == 2
        assert all(m.step_id == step_id for m in results)
    
    async def test_get_by_step_id_no_messages(self, db_session: DBAsyncSession):
        """Test retrieving messages by non-existent step_id."""
        results = await AgentMessageDAO.get_by_step_id(
            "nonexistent-step", session=db_session
        )
        
        assert len(results) == 0


class TestAgentMessageDAOGetAll:
    """Tests for AgentMessageDAO.get_all method."""
    
    async def test_get_all_returns_all(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test retrieving all agent messages."""
        for i in range(3):
            dto = AgentMessageCreate(
                collaboration_id=test_collaboration_session.id,
                content_json={"index": i},
            )
            await AgentMessageDAO.create(dto, session=db_session)
        
        results = await AgentMessageDAO.get_all(session=db_session)
        
        assert len(results) >= 3
    
    async def test_get_all_with_message_type_filter(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test retrieving messages filtered by message_type."""
        for msg_type in ["request", "response", "tool_call"]:
            dto = AgentMessageCreate(
                collaboration_id=test_collaboration_session.id,
                message_type=msg_type,
                content_json={"type": msg_type},
            )
            await AgentMessageDAO.create(dto, session=db_session)
        
        requests = await AgentMessageDAO.get_all(
            message_type="request", session=db_session
        )
        
        assert all(m.message_type == "request" for m in requests)
    
    async def test_get_all_with_pagination(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test retrieving messages with pagination."""
        for i in range(5):
            dto = AgentMessageCreate(
                collaboration_id=test_collaboration_session.id,
                content_json={"index": i},
            )
            await AgentMessageDAO.create(dto, session=db_session)
        
        page1 = await AgentMessageDAO.get_all(
            limit=2, offset=0, session=db_session
        )
        
        assert len(page1) == 2


class TestAgentMessageDAOUpdate:
    """Tests for AgentMessageDAO.update method."""
    
    async def test_update_content_json(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test updating message content_json."""
        create_dto = AgentMessageCreate(
            collaboration_id=test_collaboration_session.id,
            content_json={"old": "content"},
        )
        created = await AgentMessageDAO.create(create_dto, session=db_session)
        
        update_dto = AgentMessageUpdate(
            id=created.id,
            content_json={"new": "content"},
        )
        result = await AgentMessageDAO.update(update_dto, session=db_session)
        
        assert result is not None
        assert result.content_json == {"new": "content"}
    
    async def test_update_redaction_level(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test updating message redaction_level."""
        create_dto = AgentMessageCreate(
            collaboration_id=test_collaboration_session.id,
            content_json={"test": "data"},
        )
        created = await AgentMessageDAO.create(create_dto, session=db_session)
        
        update_dto = AgentMessageUpdate(
            id=created.id,
            redaction_level="full",
        )
        result = await AgentMessageDAO.update(update_dto, session=db_session)
        
        assert result is not None
        assert result.redaction_level == "full"
    
    async def test_update_nonexistent_returns_none(self, db_session: DBAsyncSession):
        """Test updating a non-existent message returns None."""
        update_dto = AgentMessageUpdate(
            id=uuid4(),
            content_json={"test": "data"},
        )
        result = await AgentMessageDAO.update(update_dto, session=db_session)
        
        assert result is None


class TestAgentMessageDAODelete:
    """Tests for AgentMessageDAO.delete method."""
    
    async def test_delete_existing(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test deleting an existing message."""
        create_dto = AgentMessageCreate(
            collaboration_id=test_collaboration_session.id,
            content_json={"test": "data"},
        )
        created = await AgentMessageDAO.create(create_dto, session=db_session)
        
        success = await AgentMessageDAO.delete(created.id, session=db_session)
        
        assert success is True
        
        result = await AgentMessageDAO.get_by_id(created.id, session=db_session)
        assert result is None
    
    async def test_delete_nonexistent_returns_false(self, db_session: DBAsyncSession):
        """Test deleting a non-existent message returns False."""
        success = await AgentMessageDAO.delete(uuid4(), session=db_session)
        
        assert success is False


class TestAgentMessageDAOExists:
    """Tests for AgentMessageDAO.exists method."""
    
    async def test_exists_true(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test exists returns True for existing message."""
        create_dto = AgentMessageCreate(
            collaboration_id=test_collaboration_session.id,
            content_json={"test": "data"},
        )
        created = await AgentMessageDAO.create(create_dto, session=db_session)
        
        exists = await AgentMessageDAO.exists(created.id, session=db_session)
        
        assert exists is True
    
    async def test_exists_false(self, db_session: DBAsyncSession):
        """Test exists returns False for non-existent message."""
        exists = await AgentMessageDAO.exists(uuid4(), session=db_session)
        
        assert exists is False


class TestAgentMessageDAOCount:
    """Tests for AgentMessageDAO.count method."""
    
    async def test_count_returns_correct_number(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test count returns correct number of messages."""
        initial_count = await AgentMessageDAO.count(session=db_session)
        
        for i in range(3):
            dto = AgentMessageCreate(
                collaboration_id=test_collaboration_session.id,
                content_json={"index": i},
            )
            await AgentMessageDAO.create(dto, session=db_session)
        
        final_count = await AgentMessageDAO.count(session=db_session)
        
        assert final_count == initial_count + 3


# =============================================================================
# Cascade Delete Tests
# =============================================================================

class TestCascadeDelete:
    """Tests for cascade delete behavior."""
    
    async def test_collaboration_delete_cascades_to_messages(
        self,
        db_session: DBAsyncSession,
        test_user: UserEntity,
        test_agent_instance: AgentInstance,
    ):
        """Test that deleting a collaboration session cascades to messages."""
        # Create collaboration session
        collab_dto = CollaborationSessionCreate(
            user_id=test_user.id,
            main_agent_id=test_agent_instance.id,
            session_id=f"session-{uuid4()}",
        )
        collab = await CollaborationSessionDAO.create(collab_dto, session=db_session)
        
        # Create messages
        for i in range(3):
            msg_dto = AgentMessageCreate(
                collaboration_id=collab.id,
                content_json={"index": i},
            )
            await AgentMessageDAO.create(msg_dto, session=db_session)
        
        # Verify messages exist
        messages_before = await AgentMessageDAO.get_by_collaboration_id(
            collab.id, session=db_session
        )
        assert len(messages_before) == 3
        
        # Delete collaboration
        await CollaborationSessionDAO.delete(collab.id, session=db_session)
        
        # Verify messages were cascade deleted
        messages_after = await AgentMessageDAO.get_by_collaboration_id(
            collab.id, session=db_session
        )
        assert len(messages_after) == 0


# =============================================================================
# Relationship Tests
# =============================================================================

class TestRelationships:
    """Tests for entity relationships."""
    
    async def test_messages_ordered_by_created_at(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test that messages are returned ordered by created_at."""
        import asyncio
        
        for i in range(3):
            dto = AgentMessageCreate(
                collaboration_id=test_collaboration_session.id,
                content_json={"index": i},
            )
            await AgentMessageDAO.create(dto, session=db_session)
            await asyncio.sleep(0.01)  # Small delay for distinct timestamps
        
        messages = await AgentMessageDAO.get_by_collaboration_id(
            test_collaboration_session.id, session=db_session
        )
        
        # Messages should be ordered by created_at ascending
        for i in range(len(messages) - 1):
            assert messages[i].created_at <= messages[i + 1].created_at
    
    async def test_step_id_grouping(
        self,
        db_session: DBAsyncSession,
        test_collaboration_session: CollaborationSession,
    ):
        """Test that messages can be grouped by step_id."""
        step_id = "step-group-test"
        
        # Create request-response pair
        request_dto = AgentMessageCreate(
            collaboration_id=test_collaboration_session.id,
            step_id=step_id,
            message_type="request",
            content_json={"action": "search"},
        )
        await AgentMessageDAO.create(request_dto, session=db_session)
        
        response_dto = AgentMessageCreate(
            collaboration_id=test_collaboration_session.id,
            step_id=step_id,
            message_type="response",
            content_json={"results": []},
        )
        await AgentMessageDAO.create(response_dto, session=db_session)
        
        # Create another message with different step
        other_dto = AgentMessageCreate(
            collaboration_id=test_collaboration_session.id,
            step_id="other-step",
            message_type="notification",
            content_json={"info": "broadcast"},
        )
        await AgentMessageDAO.create(other_dto, session=db_session)
        
        # Retrieve by step_id
        step_messages = await AgentMessageDAO.get_by_step_id(
            step_id, session=db_session
        )
        
        assert len(step_messages) == 2
        assert all(m.step_id == step_id for m in step_messages)