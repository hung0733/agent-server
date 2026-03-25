# pyright: reportMissingImports=false
"""
Data Access Object for LLMLevelEndpoint entity operations.

This module provides static methods for CRUD operations on LLMLevelEndpoint entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: db.dao.llm_level_endpoint_dao
"""
from __future__ import annotations

import logging
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.llm_endpoint_dto import (
    LLMEndpointWithLevel,
    LLMLevelEndpointCreate,
    LLMLevelEndpoint,
    LLMLevelEndpointUpdate,
)
from db.entity.llm_endpoint_entity import LLMEndpoint as LLMEndpointEntity
from db.entity.llm_endpoint_entity import LLMLevelEndpoint as LLMLevelEndpointEntity
from db.entity.agent_entity import AgentInstance as AgentInstanceEntity
from i18n import _

logger = logging.getLogger(__name__)


class LLMLevelEndpointDAO:
    """Data Access Object for LLMLevelEndpoint database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create a level endpoint
        level_dto = await LLMLevelEndpointDAO.create(LLMLevelEndpointCreate(...))
        
        # Get level endpoint by ID
        level = await LLMLevelEndpointDAO.get_by_id(level_id)
        
        # Get level endpoints by group ID
        levels = await LLMLevelEndpointDAO.get_by_group_id(group_id)
        
        # Get level endpoint by endpoint ID (unique)
        level = await LLMLevelEndpointDAO.get_by_endpoint_id(endpoint_id)
        
        # Update level endpoint
        updated = await LLMLevelEndpointDAO.update(LLMLevelEndpointUpdate(id=level_id, ...))
        
        # Delete level endpoint
        success = await LLMLevelEndpointDAO.delete(level_id)
    """
    
    @staticmethod
    async def create(
        dto: LLMLevelEndpointCreate,
        session: Optional[AsyncSession] = None,
    ) -> LLMLevelEndpoint:
        """Create a new LLM level endpoint.
        
        Args:
            dto: LLMLevelEndpointCreate DTO with level endpoint data.
            session: Optional async session for transaction control.
            
        Returns:
            LLMLevelEndpoint DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If unique constraint violated.
        """
        entity = LLMLevelEndpointEntity(
            group_id=dto.group_id,
            endpoint_id=dto.endpoint_id,
            difficulty_level=dto.difficulty_level,
            involves_secrets=dto.involves_secrets,
            priority=dto.priority,
            is_active=dto.is_active,
        )
        
        if session is not None:
            session.add(entity)
            await session.commit()
            await session.refresh(entity)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                s.add(entity)
                await s.commit()
                await s.refresh(entity)
            await engine.dispose()
        
        return LLMLevelEndpoint.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        level_endpoint_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[LLMLevelEndpoint]:
        """Retrieve an LLM level endpoint by ID.
        
        Args:
            level_endpoint_id: UUID of the level endpoint to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            LLMLevelEndpoint DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[LLMLevelEndpointEntity]:
            result = await s.execute(
                select(LLMLevelEndpointEntity).where(LLMLevelEndpointEntity.id == level_endpoint_id)
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
        return LLMLevelEndpoint.model_validate(entity)
    
    @staticmethod
    async def get_by_group_id(
        group_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[LLMLevelEndpoint]:
        """Retrieve all LLM level endpoints for a group.
        
        Args:
            group_id: UUID of the group.
            session: Optional async session for transaction control.
            
        Returns:
            List of LLMLevelEndpoint DTOs.
        """
        async def _query(s: AsyncSession) -> List[LLMLevelEndpointEntity]:
            result = await s.execute(
                select(LLMLevelEndpointEntity).where(LLMLevelEndpointEntity.group_id == group_id)
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
        
        return [LLMLevelEndpoint.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_by_endpoint_id(
        endpoint_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[LLMLevelEndpoint]:
        """Retrieve LLM level endpoint by endpoint ID.
        
        Note: endpoint_id has a unique constraint, so this returns a single result.
        
        Args:
            endpoint_id: UUID of the endpoint.
            session: Optional async session for transaction control.
            
        Returns:
            LLMLevelEndpoint DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[LLMLevelEndpointEntity]:
            result = await s.execute(
                select(LLMLevelEndpointEntity).where(LLMLevelEndpointEntity.endpoint_id == endpoint_id)
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
        return LLMLevelEndpoint.model_validate(entity)
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        active_only: bool = False,
        session: Optional[AsyncSession] = None,
    ) -> List[LLMLevelEndpoint]:
        """Retrieve all LLM level endpoints with pagination.
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            active_only: If True, only return active level endpoints.
            session: Optional async session for transaction control.
            
        Returns:
            List of LLMLevelEndpoint DTOs.
        """
        async def _query(s: AsyncSession) -> List[LLMLevelEndpointEntity]:
            query = select(LLMLevelEndpointEntity).limit(limit).offset(offset)
            if active_only:
                query = query.where(LLMLevelEndpointEntity.is_active == True)
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
        
        return [LLMLevelEndpoint.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: LLMLevelEndpointUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[LLMLevelEndpoint]:
        """Update an existing LLM level endpoint.
        
        Only updates fields that are provided in the DTO.
        
        Args:
            dto: LLMLevelEndpointUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated LLMLevelEndpoint DTO if entity exists, None otherwise.
            
        Raises:
            IntegrityError: If unique constraint violated.
        """
        async def _update(s: AsyncSession) -> Optional[LLMLevelEndpointEntity]:
            entity = await s.get(LLMLevelEndpointEntity, dto.id)
            if entity is None:
                return None
            
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
        return LLMLevelEndpoint.model_validate(entity)
    
    @staticmethod
    async def delete(
        level_endpoint_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete an LLM level endpoint by ID.
        
        Args:
            level_endpoint_id: UUID of the level endpoint to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(LLMLevelEndpointEntity).where(LLMLevelEndpointEntity.id == level_endpoint_id)
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
        level_endpoint_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if an LLM level endpoint exists.
        
        Args:
            level_endpoint_id: UUID of the level endpoint to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if level endpoint exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(LLMLevelEndpointEntity.id).where(LLMLevelEndpointEntity.id == level_endpoint_id)
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
        """Count total number of LLM level endpoints.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of LLM level endpoints in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(LLMLevelEndpointEntity)
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
    async def get_by_agent_instance_id(
        agent_instance_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[LLMEndpointWithLevel]:
        """Return all active endpoints for an agent, enriched with level metadata.

        Joins agent_instances → llm_level_endpoints → llm_endpoints using the
        agent's endpoint_group_id.  Both the level assignment and the endpoint
        itself must be active (is_active = true) to be included.

        Args:
            agent_instance_id: UUID of the AgentInstance (agent_db_id).
            session: Optional async session for transaction control.

        Returns:
            List of LLMEndpointWithLevel DTOs ordered by difficulty_level,
            priority descending.
        """
        async def _query(s: AsyncSession) -> List[LLMEndpointWithLevel]:
            # First, query without API key filter to see what's available
            all_rows = await s.execute(
                select(
                    LLMEndpointEntity,
                    LLMLevelEndpointEntity.difficulty_level,
                    LLMLevelEndpointEntity.involves_secrets,
                    LLMLevelEndpointEntity.priority,
                )
                .join(
                    LLMLevelEndpointEntity,
                    LLMLevelEndpointEntity.endpoint_id == LLMEndpointEntity.id,
                )
                .join(
                    AgentInstanceEntity,
                    AgentInstanceEntity.endpoint_group_id == LLMLevelEndpointEntity.group_id,
                )
                .where(
                    AgentInstanceEntity.id == agent_instance_id,
                    LLMLevelEndpointEntity.is_active.is_(True),
                    LLMEndpointEntity.is_active.is_(True),
                )
                .order_by(
                    LLMLevelEndpointEntity.difficulty_level,
                    LLMLevelEndpointEntity.priority.asc(),
                )
            )

            total_count = 0
            filtered_count = 0
            result: List[LLMEndpointWithLevel] = []

            for ep_entity, difficulty_level, involves_secrets, priority in all_rows:
                total_count += 1

                data = {
                    **{
                        c.key: getattr(ep_entity, c.key)
                        for c in ep_entity.__table__.columns
                    },
                    "difficulty_level": difficulty_level,
                    "involves_secrets": involves_secrets,
                    "priority": priority,
                }

                # Allow empty API keys for local models - set to empty string if None
                if data.get("api_key_encrypted") is None:
                    data["api_key_encrypted"] = ""

                try:
                    result.append(LLMEndpointWithLevel.model_validate(data))
                except Exception as e:
                    filtered_count += 1
                    logger.warning(
                        _("跳過端點 '%s' (難度 %d): 驗證失敗 - %s"),
                        ep_entity.name,
                        difficulty_level,
                        str(e),
                    )
                    continue

            if total_count > 0:
                logger.info(
                    _("代理 %s: 找到 %d 個端點，過濾掉 %d 個（API key 為空），保留 %d 個"),
                    agent_instance_id,
                    total_count,
                    filtered_count,
                    len(result),
                )
            else:
                logger.warning(
                    _("代理 %s: 沒有找到任何啟用的端點配置"),
                    agent_instance_id,
                )

            return result

        if session is not None:
            return await _query(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                endpoints = await _query(s)
            await engine.dispose()
            return endpoints