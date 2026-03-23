# pyright: reportMissingImports=false
"""
Data Access Object for ToolVersion entity operations.

This module provides static methods for CRUD operations on ToolVersion entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: src.db.dao.tool_version_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.tool_dto import ToolVersionCreate, ToolVersion, ToolVersionUpdate
from db.entity.tool_entity import ToolVersion as ToolVersionEntity


class ToolVersionDAO:
    """Data Access Object for ToolVersion database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create a tool version
        version_dto = await ToolVersionDAO.create(
            ToolVersionCreate(tool_id=tool_id, version="1.0.0")
        )
        
        # Get version by ID
        version = await ToolVersionDAO.get_by_id(version_id)
        
        # Get all versions for a tool
        versions = await ToolVersionDAO.get_by_tool_id(tool_id)
        
        # Get default version
        default = await ToolVersionDAO.get_default_version(tool_id)
        
        # Update version
        updated = await ToolVersionDAO.update(
            ToolVersionUpdate(id=version_id, is_default=True)
        )
        
        # Delete version
        success = await ToolVersionDAO.delete(version_id)
    """
    
    @staticmethod
    async def create(
        dto: ToolVersionCreate,
        session: Optional[AsyncSession] = None,
    ) -> ToolVersion:
        """Create a new tool version.
        
        Args:
            dto: ToolVersionCreate DTO with version data.
            session: Optional async session for transaction control.
            
        Returns:
            ToolVersion DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If foreign key constraint violated (nonexistent tool_id)
                           or unique constraint violated (duplicate default version).
        """
        entity = ToolVersionEntity(
            tool_id=dto.tool_id,
            version=dto.version,
            input_schema=dto.input_schema,
            output_schema=dto.output_schema,
            implementation_ref=dto.implementation_ref,
            config_json=dto.config_json,
            is_default=dto.is_default,
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
        
        return ToolVersion.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        version_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[ToolVersion]:
        """Retrieve a tool version by ID.
        
        Args:
            version_id: UUID of the version to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            ToolVersion DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[ToolVersionEntity]:
            result = await s.execute(
                select(ToolVersionEntity).where(ToolVersionEntity.id == version_id)
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
        return ToolVersion.model_validate(entity)
    
    @staticmethod
    async def get_by_tool_id(
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[ToolVersion]:
        """Retrieve all versions for a tool.
        
        Args:
            tool_id: UUID of the tool.
            session: Optional async session for transaction control.
            
        Returns:
            List of ToolVersion DTOs for the tool.
        """
        async def _query(s: AsyncSession) -> List[ToolVersionEntity]:
            result = await s.execute(
                select(ToolVersionEntity).where(ToolVersionEntity.tool_id == tool_id)
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
        
        return [ToolVersion.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_default_version(
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[ToolVersion]:
        """Retrieve the default version for a tool.
        
        Args:
            tool_id: UUID of the tool.
            session: Optional async session for transaction control.
            
        Returns:
            ToolVersion DTO if default exists, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[ToolVersionEntity]:
            result = await s.execute(
                select(ToolVersionEntity).where(
                    ToolVersionEntity.tool_id == tool_id,
                    ToolVersionEntity.is_default == True
                )
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
        return ToolVersion.model_validate(entity)
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[ToolVersion]:
        """Retrieve all tool versions with pagination.
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of ToolVersion DTOs.
        """
        async def _query(s: AsyncSession) -> List[ToolVersionEntity]:
            result = await s.execute(
                select(ToolVersionEntity).limit(limit).offset(offset)
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
        
        return [ToolVersion.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: ToolVersionUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[ToolVersion]:
        """Update an existing tool version.
        
        Only updates fields that are provided in the DTO.
        
        Args:
            dto: ToolVersionUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated ToolVersion DTO if entity exists, None otherwise.
            
        Raises:
            IntegrityError: If unique constraint violated (duplicate default version).
        """
        async def _update(s: AsyncSession) -> Optional[ToolVersionEntity]:
            # Fetch existing entity
            entity = await s.get(ToolVersionEntity, dto.id)
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
        return ToolVersion.model_validate(entity)
    
    @staticmethod
    async def delete(
        version_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete a tool version by ID.
        
        Args:
            version_id: UUID of the version to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(ToolVersionEntity).where(ToolVersionEntity.id == version_id)
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
        version_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if a tool version exists.
        
        Args:
            version_id: UUID of the version to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if version exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(ToolVersionEntity.id).where(ToolVersionEntity.id == version_id)
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
        """Count total number of tool versions.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of tool versions in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(ToolVersionEntity)
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
        """Count versions for a specific tool.
        
        Args:
            tool_id: UUID of the tool.
            session: Optional async session for transaction control.
            
        Returns:
            Count of versions for the tool.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(ToolVersionEntity).where(
                    ToolVersionEntity.tool_id == tool_id
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