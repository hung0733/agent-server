#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Manual DAO Verification Script.

This script tests CRUD operations on all DAOs to verify the system works correctly.
Run with: python scripts/manual_dao_verification.py
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# Import engine and session first
from db import create_engine, AsyncSession as AsyncSessionClass

# Import all entities first to resolve relationship mappings
# This ensures SQLAlchemy can resolve all forward references
from db.entity.user_entity import User as UserEntity, APIKey as APIKeyEntity
from db.entity.llm_endpoint_entity import LLMEndpointGroup, LLMEndpoint, LLMLevelEndpoint
from db.entity.agent_entity import AgentType as AgentTypeEntity, AgentInstance as AgentInstanceEntity
from db.entity.task_entity import Task as TaskEntity, TaskDependency as TaskDependencyEntity
from db.entity.tool_entity import Tool as ToolEntity

# Now import DAOs and DTOs
from db.dao.user_dao import UserDAO
from db.dao.task_dao import TaskDAO, TaskDependencyDAO
from db.dao.agent_type_dao import AgentTypeDAO
from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dao.tool_dao import ToolDAO
from db.dto.user_dto import UserCreate, UserUpdate
from db.dto.task_dto import TaskCreate, TaskUpdate, TaskDependencyCreate
from db.dto.agent_dto import AgentTypeCreate, AgentTypeUpdate, AgentInstanceCreate
from db.dto.tool_dto import ToolCreate, ToolUpdate
from db.types import TaskStatus


class TestResult:
    """Helper class to track test results."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def success(self, msg: str):
        self.passed += 1
        print(f"  ✅ PASS: {msg}")
    
    def failure(self, msg: str, error: Exception = None):
        self.failed += 1
        error_msg = f"  ❌ FAIL: {msg}"
        if error:
            error_msg += f" - {error}"
        print(error_msg)
        self.errors.append((msg, str(error) if error else None))
    
    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*60}")
        print(f"SUMMARY: {self.passed}/{total} tests passed")
        if self.errors:
            print("\nFailed tests:")
            for msg, err in self.errors:
                print(f"  - {msg}: {err}")
        return self.failed == 0


results = TestResult()
created_resources = {
    'users': [],
    'agent_types': [],
    'agent_instances': [],
    'tools': [],
    'tasks': [],
}


async def test_user_dao(session: AsyncSession):
    """Test UserDAO CRUD operations."""
    print("\n" + "="*60)
    print("Testing UserDAO CRUD Operations")
    print("="*60)
    
    # CREATE
    print("\n1. CREATE - Creating a new user...")
    try:
        user_create = UserCreate(
            username=f"testuser_{uuid4().hex[:8]}",
            email=f"test_{uuid4().hex[:8]}@example.com",
            is_active=True
        )
        created_user = await UserDAO.create(user_create, session=session)
        
        if created_user and created_user.id and created_user.username == user_create.username:
            results.success(f"Created user: {created_user.username} (ID: {created_user.id})")
            created_resources['users'].append(created_user.id)
        else:
            results.failure("User creation returned invalid data")
    except Exception as e:
        results.failure("Failed to create user", e)
        return
    
    user_id = created_user.id
    
    # READ - Get by ID
    print("\n2. READ - Fetching user by ID...")
    try:
        fetched_user = await UserDAO.get_by_id(user_id, session=session)
        if fetched_user and fetched_user.id == user_id:
            results.success(f"Fetched user by ID: {fetched_user.username}")
        else:
            results.failure("get_by_id returned None or wrong user")
    except Exception as e:
        results.failure("Failed to fetch user by ID", e)
    
    # READ - Get by email
    print("\n3. READ - Fetching user by email...")
    try:
        fetched_by_email = await UserDAO.get_by_email(user_create.email, session=session)
        if fetched_by_email and fetched_by_email.email == user_create.email:
            results.success(f"Fetched user by email: {fetched_by_email.email}")
        else:
            results.failure("get_by_email returned None or wrong user")
    except Exception as e:
        results.failure("Failed to fetch user by email", e)
    
    # UPDATE
    print("\n4. UPDATE - Updating user username...")
    try:
        import asyncio
        await asyncio.sleep(0.01)  # Ensure timestamp changes
        user_update = UserUpdate(
            id=user_id,
            username=f"updated_{uuid4().hex[:8]}"
        )
        updated_user = await UserDAO.update(user_update, session=session)
        if updated_user and updated_user.username == user_update.username:
            results.success(f"Updated username to: {updated_user.username}")
        else:
            results.failure("Update returned None or wrong data")
    except Exception as e:
        results.failure("Failed to update user", e)
    
    # EXISTS
    print("\n5. EXISTS - Checking user existence...")
    try:
        exists = await UserDAO.exists(user_id, session=session)
        if exists:
            results.success(f"User exists check passed")
        else:
            results.failure("exists() returned False for existing user")
    except Exception as e:
        results.failure("Failed to check user existence", e)
    
    # COUNT
    print("\n6. COUNT - Counting users...")
    try:
        count = await UserDAO.count(session=session)
        if count >= 1:
            results.success(f"User count: {count}")
        else:
            results.failure(f"Unexpected count: {count}")
    except Exception as e:
        results.failure("Failed to count users", e)
    
    return user_id


async def test_agent_type_dao(session: AsyncSession):
    """Test AgentTypeDAO CRUD operations."""
    print("\n" + "="*60)
    print("Testing AgentTypeDAO CRUD Operations")
    print("="*60)
    
    # CREATE
    print("\n1. CREATE - Creating a new agent type...")
    try:
        agent_type_create = AgentTypeCreate(
            name=f"TestAgent_{uuid4().hex[:8]}",
            description="Test agent type for verification",
            capabilities={"research": True, "analysis": True},
            is_active=True
        )
        created_type = await AgentTypeDAO.create(agent_type_create, session=session)
        
        if created_type and created_type.id and created_type.name == agent_type_create.name:
            results.success(f"Created agent type: {created_type.name} (ID: {created_type.id})")
            created_resources['agent_types'].append(created_type.id)
        else:
            results.failure("Agent type creation returned invalid data")
    except Exception as e:
        results.failure("Failed to create agent type", e)
        return
    
    type_id = created_type.id
    
    # READ - Get by ID
    print("\n2. READ - Fetching agent type by ID...")
    try:
        fetched = await AgentTypeDAO.get_by_id(type_id, session=session)
        if fetched and fetched.id == type_id:
            results.success(f"Fetched agent type: {fetched.name}")
        else:
            results.failure("get_by_id returned None or wrong type")
    except Exception as e:
        results.failure("Failed to fetch agent type by ID", e)
    
    # READ - Get by name
    print("\n3. READ - Fetching agent type by name...")
    try:
        fetched_by_name = await AgentTypeDAO.get_by_name(agent_type_create.name, session=session)
        if fetched_by_name and fetched_by_name.name == agent_type_create.name:
            results.success(f"Fetched by name: {fetched_by_name.name}")
        else:
            results.failure("get_by_name returned None or wrong type")
    except Exception as e:
        results.failure("Failed to fetch agent type by name", e)
    
    # UPDATE
    print("\n4. UPDATE - Updating agent type description...")
    try:
        type_update = AgentTypeUpdate(
            id=type_id,
            description="Updated description for verification"
        )
        updated = await AgentTypeDAO.update(type_update, session=session)
        if updated and "Updated" in updated.description:
            results.success(f"Updated description")
        else:
            results.failure("Update failed")
    except Exception as e:
        results.failure("Failed to update agent type", e)
    
    return type_id


async def test_tool_dao(session: AsyncSession):
    """Test ToolDAO CRUD operations."""
    print("\n" + "="*60)
    print("Testing ToolDAO CRUD Operations")
    print("="*60)
    
    # CREATE
    print("\n1. CREATE - Creating a new tool...")
    try:
        tool_create = ToolCreate(
            name=f"test_tool_{uuid4().hex[:8]}",
            description="Test tool for verification",
            is_active=True
        )
        created_tool = await ToolDAO.create(tool_create, session=session)
        
        if created_tool and created_tool.id:
            results.success(f"Created tool: {created_tool.name} (ID: {created_tool.id})")
            created_resources['tools'].append(created_tool.id)
        else:
            results.failure("Tool creation returned invalid data")
    except Exception as e:
        results.failure("Failed to create tool", e)
        return
    
    tool_id = created_tool.id
    
    # READ
    print("\n2. READ - Fetching tool by ID...")
    try:
        fetched = await ToolDAO.get_by_id(tool_id, session=session)
        if fetched and fetched.id == tool_id:
            results.success(f"Fetched tool: {fetched.name}")
        else:
            results.failure("get_by_id returned None")
    except Exception as e:
        results.failure("Failed to fetch tool", e)
    
    # UPDATE
    print("\n3. UPDATE - Updating tool...")
    try:
        tool_update = ToolUpdate(
            id=tool_id,
            description="Updated tool description"
        )
        updated = await ToolDAO.update(tool_update, session=session)
        if updated and updated.description == "Updated tool description":
            results.success(f"Updated tool description")
        else:
            results.failure("Tool update failed")
    except Exception as e:
        results.failure("Failed to update tool", e)
    
    return tool_id


async def test_task_dao(session: AsyncSession, user_id: UUID, agent_instance_id: UUID):
    """Test TaskDAO CRUD operations."""
    print("\n" + "="*60)
    print("Testing TaskDAO CRUD Operations")
    print("="*60)
    
    # CREATE
    print("\n1. CREATE - Creating a new task...")
    try:
        task_create = TaskCreate(
            user_id=user_id,
            agent_id=agent_instance_id,
            task_type="verification_test",
            status=TaskStatus.pending,
            priority="high",
            payload={"test": "data", "timestamp": datetime.now(timezone.utc).isoformat()}
        )
        created_task = await TaskDAO.create(task_create, session=session)
        
        if created_task and created_task.id:
            results.success(f"Created task: {created_task.task_type} (ID: {created_task.id})")
            created_resources['tasks'].append(created_task.id)
        else:
            results.failure("Task creation returned invalid data")
            return None
    except Exception as e:
        results.failure("Failed to create task", e)
        return None
    
    task_id = created_task.id
    
    # READ
    print("\n2. READ - Fetching task by ID...")
    try:
        fetched = await TaskDAO.get_by_id(task_id, session=session)
        if fetched and fetched.id == task_id:
            results.success(f"Fetched task: {fetched.task_type}")
        else:
            results.failure("get_by_id returned None")
    except Exception as e:
        results.failure("Failed to fetch task", e)
    
    # READ - Get by user ID
    print("\n3. READ - Fetching tasks by user ID...")
    try:
        user_tasks = await TaskDAO.get_by_user_id(user_id, session=session)
        if any(t.id == task_id for t in user_tasks):
            results.success(f"Found task in user's tasks (count: {len(user_tasks)})")
        else:
            results.failure("Task not found in user's tasks")
    except Exception as e:
        results.failure("Failed to fetch tasks by user ID", e)
    
    # UPDATE
    print("\n4. UPDATE - Updating task status...")
    try:
        task_update = TaskUpdate(
            id=task_id,
            status=TaskStatus.running
        )
        updated = await TaskDAO.update(task_update, session=session)
        if updated and updated.status == TaskStatus.running:
            results.success(f"Updated task status to: {updated.status}")
        else:
            results.failure("Task update failed")
    except Exception as e:
        results.failure("Failed to update task", e)
    
    # Test with result
    print("\n5. UPDATE - Setting task result...")
    try:
        task_update = TaskUpdate(
            id=task_id,
            status=TaskStatus.completed,
            result={"output": "Test completed successfully", "score": 100}
        )
        updated = await TaskDAO.update(task_update, session=session)
        if updated and updated.status == TaskStatus.completed and updated.result:
            results.success(f"Task completed with result")
        else:
            results.failure("Task completion failed")
    except Exception as e:
        results.failure("Failed to complete task", e)
    
    return task_id


async def test_task_dependencies(session: AsyncSession, user_id: UUID, agent_instance_id: UUID):
    """Test TaskDependencyDAO operations."""
    print("\n" + "="*60)
    print("Testing TaskDependencyDAO Operations")
    print("="*60)
    
    # Create parent and child tasks
    print("\n1. CREATE - Creating parent and child tasks for dependency test...")
    try:
        parent_task = await TaskDAO.create(
            TaskCreate(user_id=user_id, agent_id=agent_instance_id, task_type="parent_task"),
            session=session
        )
        child_task = await TaskDAO.create(
            TaskCreate(user_id=user_id, agent_id=agent_instance_id, task_type="child_task"),
            session=session
        )
        created_resources['tasks'].extend([parent_task.id, child_task.id])
        results.success(f"Created parent task {parent_task.id} and child task {child_task.id}")
    except Exception as e:
        results.failure("Failed to create tasks for dependency test", e)
        return
    
    # Create dependency
    print("\n2. CREATE - Creating task dependency...")
    try:
        dependency = await TaskDependencyDAO.create(
            TaskDependencyCreate(
                parent_task_id=parent_task.id,
                child_task_id=child_task.id,
                dependency_type="sequential"
            ),
            session=session
        )
        if dependency and dependency.id:
            results.success(f"Created dependency: parent -> child")
        else:
            results.failure("Dependency creation failed")
    except Exception as e:
        results.failure("Failed to create dependency", e)
    
    # Verify DAG operations
    print("\n3. DAG - Testing get_ancestors...")
    try:
        ancestors = await TaskDAO.get_ancestors(child_task.id, session)
        if parent_task.id in ancestors:
            results.success(f"Found parent in ancestors")
        else:
            results.failure("Parent not found in ancestors")
    except Exception as e:
        results.failure("Failed to get ancestors", e)
    
    print("\n4. DAG - Testing get_descendants...")
    try:
        descendants = await TaskDAO.get_descendants(parent_task.id, session)
        if child_task.id in descendants:
            results.success(f"Found child in descendants")
        else:
            results.failure("Child not found in descendants")
    except Exception as e:
        results.failure("Failed to get descendants", e)


async def test_agent_instance_dao(session: AsyncSession, agent_type_id: UUID, user_id: UUID):
    """Test AgentInstanceDAO CRUD operations."""
    print("\n" + "="*60)
    print("Testing AgentInstanceDAO CRUD Operations")
    print("="*60)
    
    # CREATE
    print("\n1. CREATE - Creating a new agent instance...")
    try:
        instance_create = AgentInstanceCreate(
            agent_type_id=agent_type_id,
            user_id=user_id,
            config={"model": "gpt-4", "temperature": 0.7},
            status="idle"
        )
        created_instance = await AgentInstanceDAO.create(instance_create, session=session)
        
        if created_instance and created_instance.id:
            results.success(f"Created agent instance (ID: {created_instance.id})")
            created_resources['agent_instances'].append(created_instance.id)
        else:
            results.failure("Agent instance creation returned invalid data")
    except Exception as e:
        results.failure("Failed to create agent instance", e)
        return
    
    instance_id = created_instance.id
    
    # READ
    print("\n2. READ - Fetching agent instance by ID...")
    try:
        fetched = await AgentInstanceDAO.get_by_id(instance_id, session=session)
        if fetched and fetched.id == instance_id:
            results.success(f"Fetched agent instance")
        else:
            results.failure("get_by_id returned None")
    except Exception as e:
        results.failure("Failed to fetch agent instance", e)
    
    return instance_id


async def cleanup(session: AsyncSession):
    """Clean up created test data."""
    print("\n" + "="*60)
    print("Cleanup - Removing test data...")
    print("="*60)
    
    try:
        # Delete in reverse dependency order
        if created_resources['tasks']:
            await session.execute(delete(TaskEntity).where(TaskEntity.id.in_(created_resources['tasks'])))
            print(f"  Deleted {len(created_resources['tasks'])} tasks")
        
        if created_resources['tools']:
            await session.execute(delete(ToolEntity).where(ToolEntity.id.in_(created_resources['tools'])))
            print(f"  Deleted {len(created_resources['tools'])} tools")
        
        if created_resources['agent_instances']:
            await session.execute(delete(AgentInstanceEntity).where(AgentInstanceEntity.id.in_(created_resources['agent_instances'])))
            print(f"  Deleted {len(created_resources['agent_instances'])} agent instances")
        
        if created_resources['agent_types']:
            await session.execute(delete(AgentTypeEntity).where(AgentTypeEntity.id.in_(created_resources['agent_types'])))
            print(f"  Deleted {len(created_resources['agent_types'])} agent types")
        
        if created_resources['users']:
            await session.execute(delete(UserEntity).where(UserEntity.id.in_(created_resources['users'])))
            print(f"  Deleted {len(created_resources['users'])} users")
        
        await session.commit()
        print("\n  ✅ Cleanup completed successfully")
    except Exception as e:
        print(f"\n  ❌ Cleanup failed: {e}")
        await session.rollback()


async def main():
    """Run all verification tests."""
    print("\n" + "="*60)
    print("DAO Manual Verification Script")
    print("="*60)
    print(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    
    # Create engine and session
    dsn = (
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'agentserver')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'testpass')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/{os.getenv('POSTGRES_DB', 'agentserver')}"
    )
    
    engine = create_engine(dsn=dsn)
    async_session = async_sessionmaker(engine, class_=AsyncSessionClass, expire_on_commit=False)
    
    try:
        async with async_session() as session:
            # Test UserDAO
            user_id = await test_user_dao(session)
            
            # Test AgentTypeDAO
            agent_type_id = await test_agent_type_dao(session)
            
            # Test ToolDAO
            tool_id = await test_tool_dao(session)
            
            # Test AgentInstanceDAO
            instance_id = None
            if agent_type_id and user_id:
                instance_id = await test_agent_instance_dao(session, agent_type_id, user_id)
            
            # Test TaskDAO
            if user_id and instance_id:
                task_id = await test_task_dao(session, user_id, instance_id)
                await test_task_dependencies(session, user_id, instance_id)
            
            # Cleanup
            await cleanup(session)
        
        # Print summary
        success = results.summary()
        
        if success:
            print("\n🎉 ALL DAO VERIFICATION TESTS PASSED!")
            sys.exit(0)
        else:
            print("\n⚠️  Some tests failed. Review the errors above.")
            sys.exit(1)
            
    except Exception as e:
        print(f"\n❌ Fatal error during verification: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())