# pyright: reportMissingImports=false
"""
Data Access Object for User entity operations.

This module provides static methods for CRUD operations on User entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: src.db.dao.user_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.user_dto import UserCreate, User, UserUpdate
from db.entity.user_entity import User as UserEntity


class UserDAO:
    """Data Access Object for User database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create a user
        user_dto = await UserDAO.create(UserCreate(username="john", email="john@example.com"))
        
        # Get user by ID
        user = await UserDAO.get_by_id(user_id)
        
        # Get user by email
        user = await UserDAO.get_by_email("john@example.com")
        
        # Update user
        updated = await UserDAO.update(UserUpdate(id=user_id, username="newname"))
        
        # Delete user
        success = await UserDAO.delete(user_id)
    """
    
    @staticmethod
    async def create(
        dto: UserCreate,
        session: Optional[AsyncSession] = None,
    ) -> User:
        """Create a new user.
        
        Args:
            dto: UserCreate DTO with user data.
            session: Optional async session for transaction control.
            
        Returns:
            User DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If unique constraint violated (duplicate username/email).
        """
        entity = UserEntity(
            username=dto.username,
            email=dto.email,
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
        
        return User.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        user_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[User]:
        """Retrieve a user by ID.
        
        Args:
            user_id: UUID of the user to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            User DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[UserEntity]:
            result = await s.execute(
                select(UserEntity).where(UserEntity.id == user_id)
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
        return User.model_validate(entity)
    
    @staticmethod
    async def get_by_email(
        email: str,
        session: Optional[AsyncSession] = None,
    ) -> Optional[User]:
        """Retrieve a user by email address.
        
        Args:
            email: Email address to search for.
            session: Optional async session for transaction control.
            
        Returns:
            User DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[UserEntity]:
            result = await s.execute(
                select(UserEntity).where(UserEntity.email == email)
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
        return User.model_validate(entity)
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[User]:
        """Retrieve all users with pagination.
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of User DTOs.
        """
        async def _query(s: AsyncSession) -> List[UserEntity]:
            result = await s.execute(
                select(UserEntity).limit(limit).offset(offset)
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
        
        return [User.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: UserUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[User]:
        """Update an existing user.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: UserUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated User DTO if entity exists, None otherwise.
            
        Raises:
            IntegrityError: If unique constraint violated.
        """
        async def _update(s: AsyncSession) -> Optional[UserEntity]:
            # Fetch existing entity
            entity = await s.get(UserEntity, dto.id)
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
        return User.model_validate(entity)
    
    @staticmethod
    async def delete(
        user_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete a user by ID.
        
        Note: Cascade delete will also remove all associated API keys
        and other related entities.
        
        Args:
            user_id: UUID of the user to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(UserEntity).where(UserEntity.id == user_id)
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
        user_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if a user exists.
        
        Args:
            user_id: UUID of the user to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if user exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(UserEntity.id).where(UserEntity.id == user_id)
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
        """Count total number of users.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of users in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(UserEntity)
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