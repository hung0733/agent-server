# pyright: reportMissingImports=false
"""
Data Access Object for TokenUsage entity operations.

This module provides static methods for CRUD operations on TokenUsage entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: src.db.dao.token_usage_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.token_usage_dto import TokenUsageCreate, TokenUsage, TokenUsageUpdate
from db.entity.token_usage_entity import TokenUsage as TokenUsageEntity


class TokenUsageDAO:
    """Data Access Object for TokenUsage database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Note: Token usage records are typically immutable (audit trail).
    The update method returns None for this reason.
    
    Example:
        # Create a token usage record
        dto = await TokenUsageDAO.create(TokenUsageCreate(
            user_id=user_id,
            agent_id=agent_id,
            session_id="session-123",
            model_name="gpt-4",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            estimated_cost_usd=Decimal("0.004500"),
        ))
        
        # Get by ID
        record = await TokenUsageDAO.get_by_id(record_id)
        
        # Get by user_id
        records = await TokenUsageDAO.get_by_user_id(user_id)
        
        # Get by session_id
        records = await TokenUsageDAO.get_by_session_id("session-123")
        
        # Delete
        success = await TokenUsageDAO.delete(record_id)
    """
    
    @staticmethod
    async def create(
        dto: TokenUsageCreate,
        session: Optional[AsyncSession] = None,
    ) -> TokenUsage:
        """Create a new token usage record.
        
        Args:
            dto: TokenUsageCreate DTO with token usage data.
            session: Optional async session for transaction control.
            
        Returns:
            TokenUsage DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If foreign key constraint violated (invalid user_id or agent_id).
        """
        entity = TokenUsageEntity(
            user_id=dto.user_id,
            agent_id=dto.agent_id,
            session_id=dto.session_id,
            model_name=dto.model_name,
            input_tokens=dto.input_tokens,
            output_tokens=dto.output_tokens,
            total_tokens=dto.total_tokens,
            estimated_cost_usd=dto.estimated_cost_usd,
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
        
        return TokenUsage.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        record_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[TokenUsage]:
        """Retrieve a token usage record by ID.
        
        Args:
            record_id: UUID of the record to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            TokenUsage DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[TokenUsageEntity]:
            result = await s.execute(
                select(TokenUsageEntity).where(TokenUsageEntity.id == record_id)
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
        return TokenUsage.model_validate(entity)
    
    @staticmethod
    async def get_by_user_id(
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[TokenUsage]:
        """Retrieve token usage records by user_id.
        
        Args:
            user_id: UUID of the user.
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of TokenUsage DTOs for the user.
        """
        async def _query(s: AsyncSession) -> List[TokenUsageEntity]:
            result = await s.execute(
                select(TokenUsageEntity)
                .where(TokenUsageEntity.user_id == user_id)
                .order_by(TokenUsageEntity.created_at.desc())
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
        
        return [TokenUsage.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_by_session_id(
        session_id: str,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[TokenUsage]:
        """Retrieve token usage records by session_id.
        
        Args:
            session_id: Session identifier string.
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of TokenUsage DTOs for the session.
        """
        async def _query(s: AsyncSession) -> List[TokenUsageEntity]:
            result = await s.execute(
                select(TokenUsageEntity)
                .where(TokenUsageEntity.session_id == session_id)
                .order_by(TokenUsageEntity.created_at.desc())
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
        
        return [TokenUsage.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[TokenUsage]:
        """Retrieve all token usage records with pagination.
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of TokenUsage DTOs.
        """
        async def _query(s: AsyncSession) -> List[TokenUsageEntity]:
            result = await s.execute(
                select(TokenUsageEntity)
                .order_by(TokenUsageEntity.created_at.desc())
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
        
        return [TokenUsage.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: TokenUsageUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[TokenUsage]:
        """Update a token usage record.
        
        Note: Token usage records are immutable (audit trail).
        This method returns None to indicate updates are not supported.
        
        Args:
            dto: TokenUsageUpdate DTO (ignored).
            session: Optional async session for transaction control.
            
        Returns:
            Always returns None (token usage records are immutable).
        """
        # Token usage records are immutable - return None
        return None
    
    @staticmethod
    async def delete(
        record_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete a token usage record by ID.
        
        Args:
            record_id: UUID of the record to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(TokenUsageEntity).where(TokenUsageEntity.id == record_id)
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
        record_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if a token usage record exists.
        
        Args:
            record_id: UUID of the record to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if record exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(TokenUsageEntity.id).where(TokenUsageEntity.id == record_id)
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
        """Count total number of token usage records.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of records in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(TokenUsageEntity)
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