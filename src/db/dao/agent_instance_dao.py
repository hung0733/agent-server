# pyright: reportMissingImports=false
"""
Data Access Object for AgentInstance entity operations.

This module provides static methods for CRUD operations on AgentInstance entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: src.db.dao.agent_instance_dao
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update, delete, not_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.agent_dto import AgentInstanceCreate, AgentInstance, AgentInstanceUpdate
from db.entity.agent_entity import AgentInstance as AgentInstanceEntity
from db.entity.user_entity import User as UserEntity


def _stale_busy_cutoff(now: Optional[datetime] = None) -> datetime:
    if now is None:
        now = datetime.now(UTC)
    return now - timedelta(minutes=5)


class AgentInstanceDAO:
    """Data Access Object for AgentInstance database operations.
    
    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.
    
    Example:
        # Create an agent instance
        instance_dto = await AgentInstanceDAO.create(
            AgentInstanceCreate(
                agent_type_id=agent_type_id,
                user_id=user_id,
                name="MyAgent"
            )
        )
        
        # Get instance by ID
        instance = await AgentInstanceDAO.get_by_id(instance_id)
        
        # Get instances by user
        instances = await AgentInstanceDAO.get_by_user_id(user_id)
        
        # Update instance
        updated = await AgentInstanceDAO.update(
            AgentInstanceUpdate(id=instance_id, status="busy")
        )
        
        # Delete instance
        success = await AgentInstanceDAO.delete(instance_id)
    """
    
    @staticmethod
    async def create(
        dto: AgentInstanceCreate,
        session: Optional[AsyncSession] = None,
    ) -> AgentInstance:
        """Create a new agent instance.
        
        Args:
            dto: AgentInstanceCreate DTO with instance data.
            session: Optional async session for transaction control.
            
        Returns:
            AgentInstance DTO with populated ID and generated fields.
            
        Raises:
            IntegrityError: If foreign key constraint violated (invalid agent_type_id or user_id).
        """
        entity = AgentInstanceEntity(
            agent_type_id=dto.agent_type_id,
            user_id=dto.user_id,
            name=dto.name,
            status=dto.status,
            config=dto.config,
            last_heartbeat_at=dto.last_heartbeat_at,
            is_sub_agent=dto.is_sub_agent,
            endpoint_group_id=dto.endpoint_group_id,
        )
        
        if session is not None:
            session.add(entity)
            await session.flush()
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
        
        return AgentInstance.model_validate(entity)
    
    @staticmethod
    async def get_by_id(
        instance_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentInstance]:
        """Retrieve an agent instance by ID.
        
        Args:
            instance_id: UUID of the agent instance to retrieve.
            session: Optional async session for transaction control.
            
        Returns:
            AgentInstance DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[AgentInstanceEntity]:
            result = await s.execute(
                select(AgentInstanceEntity).where(AgentInstanceEntity.id == instance_id)
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
        return AgentInstance.model_validate(entity)
    
    @staticmethod
    async def get_by_user_id(
        user_id: UUID,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[AgentInstance]:
        """Retrieve agent instances by user ID.
        
        Args:
            user_id: UUID of the user.
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of AgentInstance DTOs for the user.
        """
        async def _query(s: AsyncSession) -> List[AgentInstanceEntity]:
            result = await s.execute(
                select(AgentInstanceEntity)
                .where(AgentInstanceEntity.user_id == user_id)
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
        
        return [AgentInstance.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_by_agent_type_id(
        agent_type_id: UUID,
        limit: int = 100,
        offset: int = 0,
        session: Optional[AsyncSession] = None,
    ) -> List[AgentInstance]:
        """Retrieve agent instances by agent type ID.
        
        Args:
            agent_type_id: UUID of the agent type.
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            session: Optional async session for transaction control.
            
        Returns:
            List of AgentInstance DTOs for the agent type.
        """
        async def _query(s: AsyncSession) -> List[AgentInstanceEntity]:
            result = await s.execute(
                select(AgentInstanceEntity)
                .where(AgentInstanceEntity.agent_type_id == agent_type_id)
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
        
        return [AgentInstance.model_validate(e) for e in entities]
    
    @staticmethod
    async def get_all(
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[AgentInstance]:
        """Retrieve all agent instances with pagination.
        
        Args:
            limit: Maximum number of records to return (default 100).
            offset: Number of records to skip (default 0).
            status: Optional status filter.
            session: Optional async session for transaction control.
            
        Returns:
            List of AgentInstance DTOs.
        """
        async def _query(s: AsyncSession) -> List[AgentInstanceEntity]:
            query = select(AgentInstanceEntity)
            if status is not None:
                query = query.where(AgentInstanceEntity.status == status)
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
        
        return [AgentInstance.model_validate(e) for e in entities]
    
    @staticmethod
    async def update(
        dto: AgentInstanceUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentInstance]:
        """Update an existing agent instance.
        
        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.
        
        Args:
            dto: AgentInstanceUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.
            
        Returns:
            Updated AgentInstance DTO if entity exists, None otherwise.
        """
        async def _update(s: AsyncSession) -> Optional[AgentInstanceEntity]:
            # Fetch existing entity
            entity = await s.get(AgentInstanceEntity, dto.id)
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
        return AgentInstance.model_validate(entity)
    
    @staticmethod
    async def delete(
        instance_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete an agent instance by ID.
        
        Args:
            instance_id: UUID of the agent instance to delete.
            session: Optional async session for transaction control.
            
        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(AgentInstanceEntity).where(AgentInstanceEntity.id == instance_id)
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
        instance_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if an agent instance exists.
        
        Args:
            instance_id: UUID of the agent instance to check.
            session: Optional async session for transaction control.
            
        Returns:
            True if agent instance exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(AgentInstanceEntity.id).where(AgentInstanceEntity.id == instance_id)
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
        """Count total number of agent instances.
        
        Args:
            session: Optional async session for transaction control.
            
        Returns:
            Total count of agent instances in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(AgentInstanceEntity)
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
    async def get_by_agent_id(
        agent_id: str,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentInstance]:
        """Retrieve an agent instance by its unique agent_id string.

        Args:
            agent_id: String identifier of the agent (e.g., 'butler-001').
            session: Optional async session for transaction control.

        Returns:
            AgentInstance DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[AgentInstanceEntity]:
            result = await s.execute(
                select(AgentInstanceEntity).where(AgentInstanceEntity.agent_id == agent_id)
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
        return AgentInstance.model_validate(entity)

    @staticmethod
    async def get_by_phones(
        sender_phone_no: str,
        receiver_phone_no: str,
        session: Optional[AsyncSession] = None,
    ) -> Optional[AgentInstance]:
        """Retrieve an agent instance by verifying both phone numbers.

        Ensures only the owning user (matched by sender_phone_no) can
        interact with the agent at receiver_phone_no.

        Args:
            sender_phone_no:   The user's phone number (message sender).
            receiver_phone_no: The agent's phone number (message receiver).
            session:           Optional async session for transaction control.

        Returns:
            AgentInstance DTO if both phones match a valid pairing, None otherwise.
        """
        import logging
        logger = logging.getLogger(__name__)
        from i18n import _

        async def _query(s: AsyncSession) -> Optional[AgentInstanceEntity]:
            result = await s.execute(
                select(AgentInstanceEntity)
                .join(UserEntity, AgentInstanceEntity.user_id == UserEntity.id)
                .where(
                    AgentInstanceEntity.phone_no == receiver_phone_no,
                    UserEntity.phone_no == sender_phone_no,
                    AgentInstanceEntity.whatsapp_key.isnot(None),
                    AgentInstanceEntity.whatsapp_key != "",
                )
            )
            entity = result.scalar_one_or_none()

            logger.debug(
                _("SQL query result - sender=%s, receiver=%s, found=%s"),
                sender_phone_no,
                receiver_phone_no,
                entity is not None,
            )

            # If not found, debug by checking what exists in DB
            if entity is None:
                # Check all users
                users_result = await s.execute(select(UserEntity))
                all_users = users_result.scalars().all()
                logger.debug(
                    _("All users in DB (total=%d):"),
                    len(all_users),
                )
                for user in all_users:
                    logger.debug(
                        _("  User: id=%s, username=%s, phone_no=%s"),
                        user.id,
                        user.username,
                        user.phone_no,
                    )

                # Check all agent instances
                instances_result = await s.execute(select(AgentInstanceEntity))
                all_instances = instances_result.scalars().all()
                logger.debug(
                    _("All agent instances in DB (total=%d):"),
                    len(all_instances),
                )
                for inst in all_instances:
                    logger.debug(
                        _("  AgentInstance: id=%s, user_id=%s, phone_no=%s, whatsapp_key=%s"),
                        inst.id,
                        inst.user_id,
                        inst.phone_no,
                        inst.whatsapp_key[:10] + "..." if inst.whatsapp_key else None,
                    )

            return entity

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
        return AgentInstance.model_validate(entity)

    @staticmethod
    async def get_with_whatsapp_key(
        session: Optional[AsyncSession] = None,
    ) -> List[AgentInstance]:
        """Return all active agent instances that have a whatsapp_key set."""

        async def _query(s: AsyncSession) -> List[AgentInstanceEntity]:
            result = await s.execute(
                select(AgentInstanceEntity).where(
                    AgentInstanceEntity.whatsapp_key.isnot(None),
                    AgentInstanceEntity.whatsapp_key != "",
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

        return [AgentInstance.model_validate(e) for e in entities]

    @staticmethod
    async def get_idle_agents(
        session: Optional[AsyncSession] = None,
    ) -> List[AgentInstance]:
        """
        Retrieve all agent instances with status 'idle'.

        Args:
            session: Optional async session for transaction control.

        Returns:
            List of AgentInstance DTOs that are currently idle.
        """
        async def _query(s: AsyncSession) -> List[AgentInstanceEntity]:
            result = await s.execute(
                select(AgentInstanceEntity).where(
                    AgentInstanceEntity.status == "idle"
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

        return [AgentInstance.model_validate(e) for e in entities]

    @staticmethod
    async def claim_agent_for_task(
        agent_instance_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """
        Atomically claim an agent for task execution if it is idle.

        This method uses optimistic locking to ensure only idle agents
        are claimed, preventing race conditions in concurrent environments.

        Args:
            agent_instance_id: UUID of the agent instance to claim.
            session: Optional async session for transaction control.

        Returns:
            True if agent was successfully claimed (idle -> busy), False otherwise.
        """
        from i18n import _
        import logging
        logger = logging.getLogger(__name__)

        async def _claim(s: AsyncSession) -> bool:
            # Use UPDATE with WHERE condition for atomic claim
            from sqlalchemy import update as sql_update
            stale_before = _stale_busy_cutoff()
            stmt = (
                sql_update(AgentInstanceEntity)
                .where(
                    AgentInstanceEntity.id == agent_instance_id,
                    or_(
                        AgentInstanceEntity.status == "idle",
                        (
                            AgentInstanceEntity.status == "busy"
                        )
                        & (
                            func.coalesce(
                                AgentInstanceEntity.last_heartbeat_at,
                                AgentInstanceEntity.updated_at,
                                AgentInstanceEntity.created_at,
                            )
                            < stale_before
                        ),
                    ),
                )
                .values(status="busy", updated_at=func.now())
            )
            result = await s.execute(stmt)
            await s.commit()

            claimed = result.rowcount > 0
            logger.debug(
                _("認領 agent 結果: agent_id=%s, claimed=%s"),
                agent_instance_id,
                claimed,
            )
            return claimed

        if session is not None:
            return await _claim(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                claimed = await _claim(s)
            await engine.dispose()
            return claimed

    @staticmethod
    async def release_agent(
        agent_instance_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """
        Release an agent back to idle status after task completion.

        Args:
            agent_instance_id: UUID of the agent instance to release.
            session: Optional async session for transaction control.

        Returns:
            True if agent was successfully released, False if not found.
        """
        from i18n import _
        import logging
        logger = logging.getLogger(__name__)

        async def _release(s: AsyncSession) -> bool:
            from sqlalchemy import update as sql_update
            stmt = (
                sql_update(AgentInstanceEntity)
                .where(AgentInstanceEntity.id == agent_instance_id)
                .values(status="idle")
            )
            result = await s.execute(stmt)
            await s.commit()

            released = result.rowcount > 0
            logger.debug(
                _("釋放 agent 結果: agent_id=%s, released=%s"),
                agent_instance_id,
                released,
            )
            return released

        if session is not None:
            return await _release(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                released = await _release(s)
            await engine.dispose()
            return released
