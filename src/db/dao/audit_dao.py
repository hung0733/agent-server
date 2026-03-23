# pyright: reportMissingImports=false
"""
Data Access Object for AuditLog entity operations.

This module provides static methods for CRUD operations on AuditLog entities.
All methods return DTOs and accept optional session parameters for transaction control.

Note: Audit logs are append-only, so there are no update or delete methods.

Import path: src.db.dao.audit_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.audit_dto import AuditLogCreate, AuditLog
from db.entity.audit_entity import AuditLog as AuditLogEntity


class AuditLogDAO:
    """Data Access Object for AuditLog database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Audit logs are append-only - no update or delete operations are provided.
    
    Example:
        # Create an audit log entry
        log_dto = await AuditLogDAO.create(AuditLogCreate(
            actor_type=ActorType.user,
            actor_id=user_id,
            action="create",
            resource_type="task",
            resource_id=task_id,
        ))
        
        # Get audit log by ID
        log = await AuditLogDAO.get_by_id(log_id)
        
        # Get audit logs by user
        logs = await AuditLogDAO.get_by_user(user_id)
        
        # Get audit logs by resource
        logs = await AuditLogDAO.get_by_resource("task", task_id)
    """
    
    @staticmethod
    async def create(
        dto: AuditLogCreate,
        session: Optional[AsyncSession] = None,
    ) -> AuditLog:
        """Create a new audit log entry.
        
        Args:
            dto: AuditLogCreate DTO with audit log data.
            session: Optional async session for transaction control.
            
        Returns:
            AuditLog DTO with populated ID and generated fields.
        """
        entity = AuditLogEntity(
            user_id=dto.user_id,
            actor_type=dto.actor_type,
            actor_id=dto.actor_id,
            action=dto.action,
            resource_type=dto.resource_type,
            resource_id=dto.resource_id,
            old_values=dto.old_values,
            new_values=dto.new_values,
            ip_address=dto.ip_address,
        )
        
        if session is not None:
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
        else:
            # Create internal session if none provided
            from src.db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                s.add(entity)
                await s.commit()
                await s.refresh(entity)
            await engine.dispose()
        
        return AuditLog.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        log_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AuditLog]:
        """Retrieve an audit log by ID.
        
        Args:
            log_id: UUID of the audit log to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            AuditLog DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[AuditLogEntity]:
            result = await s.execute(
                select(AuditLogEntity).where(AuditLogEntity.id == log_id)
            )
            return result.scalar_one_or_none()
        
        if session is not None:
            entity = await _query(session)
        else:
            from src.db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entity = await _query(s)
            await engine.dispose()
        
        if entity is None:
            return None
        return AuditLog.model_validate(entity)
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[AuditLog]:
        """Retrieve all audit logs with pagination.
        
        Results are ordered by created_at descending (most recent first).
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of AuditLog DTOs.
        """
        async def _query(s: AsyncSession) -> List[AuditLogEntity]:
            result = await s.execute(
                select(AuditLogEntity)
                .order_by(AuditLogEntity.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all())
        
        if session is not None:
            entities = await _query(session)
        else:
            from src.db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entities = await _query(s)
            await engine.dispose()
        
        return [AuditLog.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_by_user(
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[AuditLog]:
        """Retrieve audit logs for a specific user.
        
        Results are ordered by created_at descending (most recent first).
        
        Args:
            user_id: UUID of the user to filter by.
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of AuditLog DTOs for the specified user.
        """
        async def _query(s: AsyncSession) -> List[AuditLogEntity]:
            result = await s.execute(
                select(AuditLogEntity)
                .where(AuditLogEntity.user_id == user_id)
                .order_by(AuditLogEntity.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all())
        
        if session is not None:
            entities = await _query(session)
        else:
            from src.db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entities = await _query(s)
            await engine.dispose()
        
        return [AuditLog.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_by_resource(
        resource_type: str,
        resource_id: UUID,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[AuditLog]:
        """Retrieve audit logs for a specific resource.
        
        Results are ordered by created_at descending (most recent first).
        
        Args:
            resource_type: Type of resource (e.g., 'user', 'task', 'agent').
            resource_id: UUID of the resource.
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of AuditLog DTOs for the specified resource.
        """
        async def _query(s: AsyncSession) -> List[AuditLogEntity]:
            result = await s.execute(
                select(AuditLogEntity)
                .where(
                    AuditLogEntity.resource_type == resource_type,
                    AuditLogEntity.resource_id == resource_id,
                )
                .order_by(AuditLogEntity.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return list(result.scalars().all())
        
        if session is not None:
            entities = await _query(session)
        else:
            from src.db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                entities = await _query(s)
            await engine.dispose()
        
        return [AuditLog.model_validate(e) for e in entities]
    
    @staticmethod
    async def count(
        session: Optional[AsyncSession] = None,
    ) -> int:
        """Count total number of audit logs.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of audit logs in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(AuditLogEntity)
            )
            return result.scalar() or 0
        
        if session is not None:
            return await _query(session)
        else:
            from src.db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                count = await _query(s)
            await engine.dispose()
            return count
    
    @staticmethod
    async def exists(
        log_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if an audit log exists.
        
        Args:
            log_id: UUID of the audit log to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if audit log exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(AuditLogEntity.id).where(AuditLogEntity.id == log_id)
            )
            return result.scalar() is not None
        
        if session is not None:
            return await _query(session)
        else:
            from src.db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                exists = await _query(s)
            await engine.dispose()
            return exists