# pyright: reportMissingImports=false
"""
Data Access Object for APIKey entity operations.

This module provides static methods for CRUD operations on APIKey entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: src.db.dao.api_key_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.user_dto import APIKeyCreate, APIKey, APIKeyUpdate
from db.entity.user_entity import APIKey as APIKeyEntity


class APIKeyDAO:
    """Data Access Object for APIKey database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create an API key
        key_dto = await APIKeyDAO.create(
            APIKeyCreate(user_id=user_id, key_hash="sha256:...")
        )
        
        # Get API key by ID
        key = await APIKeyDAO.get_by_id(key_id)
        
        # Get all keys for a user
        keys = await APIKeyDAO.get_by_user_id(user_id)
        
        # Update API key
        updated = await APIKeyDAO.update(APIKeyUpdate(id=key_id, name="New Name"))
        
        # Delete API key
        success = await APIKeyDAO.delete(key_id)
    """
    
    @staticmethod
    async def create(
        dto: APIKeyCreate,
        session: Optional[AsyncSession] = None,
    ) -> APIKey:
        """Create a new API key.
        
        Args:
            dto: APIKeyCreate DTO with key data.
            session: Optional async session for transaction control.
            
        Returns:
            APIKey DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If foreign key constraint violated (invalid user_id).
        """
        entity = APIKeyEntity(
            user_id=dto.user_id,
            key_hash=dto.key_hash,
            name=dto.name,
            is_active=dto.is_active,
            last_used_at=dto.last_used_at,
            expires_at=dto.expires_at,
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
        
        return APIKey.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        key_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[APIKey]:
        """Retrieve an API key by ID.
        
        Args:
            key_id: UUID of the API key to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            APIKey DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[APIKeyEntity]:
            result = await s.execute(
                select(APIKeyEntity).where(APIKeyEntity.id == key_id)
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
        return APIKey.model_validate(entity)
    
    @staticmethod
    async def get_by_user_id(
        user_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[APIKey]:
        """Retrieve all API keys for a specific user.
        
        Args:
            user_id: UUID of the user.
            session: Optional async session for transaction control.
            
        Returns:
            List of APIKey DTOs for the user.
        """
        async def _query(s: AsyncSession) -> List[APIKeyEntity]:
            result = await s.execute(
                select(APIKeyEntity).where(APIKeyEntity.user_id == user_id)
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
        
        return [APIKey.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[APIKey]:
        """Retrieve all API keys with pagination.
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of APIKey DTOs.
        """
        async def _query(s: AsyncSession) -> List[APIKeyEntity]:
            result = await s.execute(
                select(APIKeyEntity).limit(limit).offset(offset)
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
        
        return [APIKey.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: APIKeyUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[APIKey]:
        """Update an existing API key.
        
        Only updates fields that are provided in the DTO.
        
        Args:
            dto: APIKeyUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated APIKey DTO if entity exists, None otherwise.
        """
        async def _update(s: AsyncSession) -> Optional[APIKeyEntity]:
            # Fetch existing entity
            entity = await s.get(APIKeyEntity, dto.id)
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
        return APIKey.model_validate(entity)
    
    @staticmethod
    async def delete(
        key_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete an API key by ID.
        
        Args:
            key_id: UUID of the API key to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(APIKeyEntity).where(APIKeyEntity.id == key_id)
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
        key_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if an API key exists.
        
        Args:
            key_id: UUID of the API key to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if key exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(APIKeyEntity.id).where(APIKeyEntity.id == key_id)
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
        """Count total number of API keys.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of API keys in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(APIKeyEntity)
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
    async def get_active_keys_for_user(
        user_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[APIKey]:
        """Retrieve all active API keys for a specific user.
        
        Args:
            user_id: UUID of the user.
            session: Optional async session for transaction control.
            
        Returns:
            List of active APIKey DTOs for the user.
        """
        async def _query(s: AsyncSession) -> List[APIKeyEntity]:
            result = await s.execute(
                select(APIKeyEntity).where(
                    APIKeyEntity.user_id == user_id,
                    APIKeyEntity.is_active == True,
                )
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
        
        return [APIKey.model_validate(e) for e in entities]