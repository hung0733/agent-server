# pyright: reportMissingImports=false
"""
Data Access Object for MCP Client entity operations.

This module provides static methods for CRUD operations on MCP Client entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: src.db.dao.mcp_client_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.mcp_client_dto import MCPClientCreate, MCPClient, MCPClientUpdate
from db.entity.mcp_client_entity import MCPClient as MCPClientEntity


class MCPClientDAO:
    """Data Access Object for MCP Client database operations.

    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.

    Example:
        # Create a client
        client_dto = await MCPClientDAO.create(
            MCPClientCreate(
                user_id=user_id,
                name="filesystem-mcp",
                protocol="http",
                base_url="http://localhost:3000",
            )
        )

        # Get client by ID
        client = await MCPClientDAO.get_by_id(client_id)

        # Update client
        updated = await MCPClientDAO.update(
            MCPClientUpdate(id=client_id, status="connected")
        )

        # Delete client
        success = await MCPClientDAO.delete(client_id)
    """

    @staticmethod
    async def create(
        dto: MCPClientCreate,
        session: Optional[AsyncSession] = None,
    ) -> MCPClient:
        """Create a new MCP client.

        Args:
            dto: MCPClientCreate DTO with client data.
            session: Optional async session for transaction control.

        Returns:
            MCPClient DTO with populated ID and generated fields.

        Raises:
            IntegrityError: If foreign key constraint violated.
        """
        entity = MCPClientEntity(
            user_id=dto.user_id,
            name=dto.name,
            description=dto.description,
            protocol=dto.protocol,
            base_url=dto.base_url,
            api_key_encrypted=dto.api_key_encrypted,
            headers=dto.headers or {},
            auth_type=dto.auth_type,
            auth_config=dto.auth_config or {},
            status=dto.status,
            last_error=dto.last_error,
            client_metadata=dto.client_metadata or {},
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

        return MCPClient.model_validate(entity)

    @staticmethod
    async def get_by_id(
        client_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[MCPClient]:
        """Retrieve an MCP client by ID.

        Args:
            client_id: UUID of the client to retrieve.
            session: Optional async session for transaction control.

        Returns:
            MCPClient DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[MCPClientEntity]:
            result = await s.execute(
                select(MCPClientEntity).where(MCPClientEntity.id == client_id)
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
        return MCPClient.model_validate(entity)

    @staticmethod
    async def get_by_user(
        user_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[MCPClient]:
        """Retrieve all MCP clients for a user.

        Args:
            user_id: UUID of the user.
            session: Optional async session for transaction control.

        Returns:
            List of MCPClient DTOs.
        """
        async def _query(s: AsyncSession) -> List[MCPClientEntity]:
            result = await s.execute(
                select(MCPClientEntity).where(MCPClientEntity.user_id == user_id)
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

        return [MCPClient.model_validate(e) for e in entities]

    @staticmethod
    async def get_active(
        user_id: Optional[UUID] = None,
        session: Optional[AsyncSession] = None,
    ) -> List[MCPClient]:
        """Retrieve all active MCP clients, optionally filtered by user.

        Args:
            user_id: Optional user UUID to filter by.
            session: Optional async session for transaction control.

        Returns:
            List of active MCPClient DTOs.
        """
        async def _query(s: AsyncSession) -> List[MCPClientEntity]:
            query = select(MCPClientEntity).where(MCPClientEntity.is_active == True)
            if user_id is not None:
                query = query.where(MCPClientEntity.user_id == user_id)
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

        return [MCPClient.model_validate(e) for e in entities]

    @staticmethod
    async def update(
        dto: MCPClientUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[MCPClient]:
        """Update an existing MCP client.

        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.

        Args:
            dto: MCPClientUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.

        Returns:
            Updated MCPClient DTO if entity exists, None otherwise.

        Raises:
            IntegrityError: If constraint violated.
        """
        async def _update(s: AsyncSession) -> Optional[MCPClientEntity]:
            # Fetch existing entity
            entity = await s.get(MCPClientEntity, dto.id)
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
        return MCPClient.model_validate(entity)

    @staticmethod
    async def delete(
        client_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete an MCP client by ID.

        Note: Cascade delete will also remove all associated MCP tools.

        Args:
            client_id: UUID of the client to delete.
            session: Optional async session for transaction control.

        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(MCPClientEntity).where(MCPClientEntity.id == client_id)
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
        client_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Check if an MCP client exists.

        Args:
            client_id: UUID of the client to check.
            session: Optional async session for transaction control.

        Returns:
            True if client exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(MCPClientEntity.id).where(MCPClientEntity.id == client_id)
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
        """Count total number of MCP clients.

        Args:
            session: Optional async session for transaction control.

        Returns:
            Total count of MCP clients in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(MCPClientEntity)
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
