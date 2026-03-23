# pyright: reportMissingImports=false
"""
Data Access Object for ToolCall entity operations.

This module provides static methods for CRUD operations on ToolCall entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: db.dao.tool_call_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.tool_call_dto import ToolCall, ToolCallCreate, ToolCallUpdate
from db.entity.tool_call_entity import ToolCall as ToolCallEntity


class ToolCallDAO:
    """Data Access Object for ToolCall database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create a tool call
        call_dto = await ToolCallDAO.create(
            ToolCallCreate(task_id=task_id, tool_id=tool_id)
        )
        
        # Get tool call by ID
        call = await ToolCallDAO.get_by_id(call_id)
        
        # Get tool calls by task ID
        calls = await ToolCallDAO.get_by_task_id(task_id)
        
        # Get tool calls by tool ID
        calls = await ToolCallDAO.get_by_tool_id(tool_id)
        
        # Update tool call
        updated = await ToolCallDAO.update(
            ToolCallUpdate(id=call_id, status="completed", output={"result": "data"})
        )
        
        # Delete tool call
        success = await ToolCallDAO.delete(call_id)
        
        # Count operations
        total = await ToolCallDAO.count()
        by_task = await ToolCallDAO.count_by_task(task_id)
        by_tool = await ToolCallDAO.count_by_tool(tool_id)
    """
    
    @staticmethod
    async def create(
        dto: ToolCallCreate,
        session: Optional[AsyncSession] = None,
    ) -> ToolCall:
        """Create a new tool call.
        
        Args:
            dto: ToolCallCreate DTO with tool call data.
            session: Optional async session for transaction control.
            
        Returns:
            ToolCall DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If foreign key constraint violated (nonexistent task or tool).
        """
        entity = ToolCallEntity(
            task_id=dto.task_id,
            tool_id=dto.tool_id,
            tool_version_id=dto.tool_version_id,
            input=dto.input,
            output=dto.output,
            status=dto.status,
            error_message=dto.error_message,
            duration_ms=dto.duration_ms,
        )
        
        if session is not None:
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
        else:
            # Create internal session if none provided
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                s.add(entity)
                await s.commit()
                await s.refresh(entity)
            await engine.dispose()
        
        return ToolCall.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        tool_call_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[ToolCall]:
        """Retrieve a tool call by ID.
        
        Args:
            tool_call_id: UUID of the tool call to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            ToolCall DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[ToolCallEntity]:
            result = await s.execute(
                select(ToolCallEntity).where(ToolCallEntity.id == tool_call_id)
            )
            return result.scalar_one_or_none()
        
        if session is not None:
            entity = await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entity = await _query(s)
            await engine.dispose()
        
        if entity is None:
            return None
        return ToolCall.model_validate(entity)
    
    @staticmethod
    async def get_by_task_id(
        task_id: UUID,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[ToolCall]:
        """Retrieve tool calls by task ID.
        
        Args:
            task_id: UUID of the task.
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of ToolCall DTOs for the task.
        """
        async def _query(s: AsyncSession) -> List[ToolCallEntity]:
            result = await s.execute(
                select(ToolCallEntity)
                .where(ToolCallEntity.task_id == task_id)
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all())
        
        if session is not None:
            entities = await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entities = await _query(s)
            await engine.dispose()
        
        return [ToolCall.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_by_tool_id(
        tool_id: UUID,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[ToolCall]:
        """Retrieve tool calls by tool ID.
        
        Args:
            tool_id: UUID of the tool.
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of ToolCall DTOs for the tool.
        """
        async def _query(s: AsyncSession) -> List[ToolCallEntity]:
            result = await s.execute(
                select(ToolCallEntity)
                .where(ToolCallEntity.tool_id == tool_id)
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all())
        
        if session is not None:
            entities = await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entities = await _query(s)
            await engine.dispose()
        
        return [ToolCall.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[ToolCall]:
        """Retrieve all tool calls with optional filtering.
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            status: Optional status filter ('pending', 'running', 'completed', 'failed').
            session: Optional async session for transaction control.
            
        Returns:
            List of ToolCall DTOs.
        """
        async def _query(s: AsyncSession) -> List[ToolCallEntity]:
            query = select(ToolCallEntity)
            if status is not None:
                query = query.where(ToolCallEntity.status == status)
            query = query.limit(limit).offset(offset)
            result = await s.execute(query)
            return list(result.scalars().all())
        
        if session is not None:
            entities = await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entities = await _query(s)
            await engine.dispose()
        
        return [ToolCall.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: ToolCallUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[ToolCall]:
        """Update an existing tool call.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: ToolCallUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated ToolCall DTO if entity exists, None otherwise.
        """
        async def _update(s: AsyncSession) -> Optional[ToolCallEntity]:
            # Fetch existing entity
            entity = await s.get(ToolCallEntity, dto.id)
            if entity is None:
                return None
            
            # Update only provided fields
            update_data = dto.model_dump(exclude_unset=True, exclude={'id'})
            for field, value in update_data.items():
                if hasattr(entity, field):
                    setattr(entity, field, value)
            
            await s.commit()
            await s.refresh(entity)
            return entity
        
        if session is not None:
            entity = await _update(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entity = await _update(s)
            await engine.dispose()
        
        if entity is None:
            return None
        return ToolCall.model_validate(entity)
    
    @staticmethod
    async def delete(
        tool_call_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete a tool call by ID.
        
        Args:
            tool_call_id: UUID of the tool call to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(ToolCallEntity).where(ToolCallEntity.id == tool_call_id)
            result = await s.execute(stmt)
            await s.commit()
            return result.rowcount > 0
        
        if session is not None:
            return await _delete(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                success = await _delete(s)
            await engine.dispose()
            return success
    
    @staticmethod
    async def exists(
        tool_call_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if a tool call exists.
        
        Args:
            tool_call_id: UUID of the tool call to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if tool call exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(ToolCallEntity.id).where(ToolCallEntity.id == tool_call_id)
            )
            return result.scalar() is not None
        
        if session is not None:
            return await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                exists = await _query(s)
            await engine.dispose()
            return exists
    
    @staticmethod
    async def count(
        session: Optional[AsyncSession] = None,
    ) -> int:
        """Count total number of tool calls.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of tool calls in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(ToolCallEntity)
            )
            return result.scalar() or 0
        
        if session is not None:
            return await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                count = await _query(s)
            await engine.dispose()
            return count
    
    @staticmethod
    async def count_by_task(
        task_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> int:
        """Count tool calls for a specific task.
        
        Args:
            task_id: UUID of the task.
            session: Optional async session for transaction control.
            
        Returns:
            Count of tool calls for the task.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(ToolCallEntity).where(
                    ToolCallEntity.task_id == task_id
                )
            )
            return result.scalar() or 0
        
        if session is not None:
            return await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                count = await _query(s)
            await engine.dispose()
            return count
    
    @staticmethod
    async def count_by_tool(
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> int:
        """Count tool calls for a specific tool.
        
        Args:
            tool_id: UUID of the tool.
            session: Optional async session for transaction control.
            
        Returns:
            Count of tool calls for the tool.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(ToolCallEntity).where(
                    ToolCallEntity.tool_id == tool_id
                )
            )
            return result.scalar() or 0
        
        if session is not None:
            return await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                count = await _query(s)
            await engine.dispose()
            return count