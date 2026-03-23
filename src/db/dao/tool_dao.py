# pyright: reportMissingImports=false
"""
Data Access Object for Tool entity operations.

This module provides static methods for CRUD operations on Tool entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: src.db.dao.tool_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.tool_dto import ToolCreate, Tool, ToolUpdate
from db.entity.tool_entity import Tool as ToolEntity


class ToolDAO:
    """Data Access Object for Tool database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create a tool
        tool_dto = await ToolDAO.create(ToolCreate(name="web_search"))
        
        # Get tool by ID
        tool = await ToolDAO.get_by_id(tool_id)
        
        # Get tool by name
        tool = await ToolDAO.get_by_name("web_search")
        
        # Update tool
        updated = await ToolDAO.update(ToolUpdate(id=tool_id, name="new_name"))
        
        # Delete tool
        success = await ToolDAO.delete(tool_id)
    """
    
    @staticmethod
    async def create(
        dto: ToolCreate,
        session: Optional[AsyncSession] = None,
    ) -> Tool:
        """Create a new tool.
        
        Args:
            dto: ToolCreate DTO with tool data.
            session: Optional async session for transaction control.
            
        Returns:
            Tool DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If unique constraint violated (duplicate name).
        """
        entity = ToolEntity(
            name=dto.name,
            description=dto.description,
            is_active=dto.is_active,
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
        
        return Tool.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[Tool]:
        """Retrieve a tool by ID.
        
        Args:
            tool_id: UUID of the tool to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            Tool DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[ToolEntity]:
            result = await s.execute(
                select(ToolEntity).where(ToolEntity.id == tool_id)
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
        return Tool.model_validate(entity)
    
    @staticmethod
    async def get_by_name(
        name: str,
        session: Optional[AsyncSession] = None,
    ) -> Optional[Tool]:
        """Retrieve a tool by name.
        
        Args:
            name: Name of the tool to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            Tool DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[ToolEntity]:
            result = await s.execute(
                select(ToolEntity).where(ToolEntity.name == name)
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
        return Tool.model_validate(entity)
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[Tool]:
        """Retrieve all tools with pagination.
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of Tool DTOs.
        """
        async def _query(s: AsyncSession) -> List[ToolEntity]:
            result = await s.execute(
                select(ToolEntity).limit(limit).offset(offset)
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
        
        return [Tool.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_active(
        session: Optional[AsyncSession] = None,
    ) -> List[Tool]:
        """Retrieve all active tools.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            List of active Tool DTOs.
        """
        async def _query(s: AsyncSession) -> List[ToolEntity]:
            result = await s.execute(
                select(ToolEntity).where(ToolEntity.is_active == True)
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
        
        return [Tool.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: ToolUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[Tool]:
        """Update an existing tool.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: ToolUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated Tool DTO if entity exists, None otherwise.
            
        Raises:
            IntegrityError: If unique constraint violated.
        """
        async def _update(s: AsyncSession) -> Optional[ToolEntity]:
            # Fetch existing entity
            entity = await s.get(ToolEntity, dto.id)
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
        return Tool.model_validate(entity)
    
    @staticmethod
    async def delete(
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete a tool by ID.
        
        Note: Cascade delete will also remove all associated tool versions.
        
        Args:
            tool_id: UUID of the tool to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(ToolEntity).where(ToolEntity.id == tool_id)
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
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if a tool exists.
        
        Args:
            tool_id: UUID of the tool to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if tool exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(ToolEntity.id).where(ToolEntity.id == tool_id)
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
        """Count total number of tools.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of tools in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(ToolEntity)
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