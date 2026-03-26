# pyright: reportMissingImports=false
"""
Data Access Object for MCP Tool entity operations.

This module provides static methods for CRUD operations on MCP Tool entities.
All methods return DTOs and accept optional session parameters for transaction control.

Import path: src.db.dao.mcp_tool_dao
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db.dto.mcp_tool_dto import MCPToolCreate, MCPTool, MCPToolUpdate
from db.entity.mcp_tool_entity import MCPTool as MCPToolEntity


class MCPToolDAO:
    """Data Access Object for MCP Tool database operations.

    All methods are static and can accept an existing session for
    transaction control, or create a new session internally.

    Example:
        # Create a tool mapping
        tool_dto = await MCPToolDAO.create(
            MCPToolCreate(
                mcp_client_id=client_id,
                tool_id=tool_id,
                mcp_tool_name="read_file",
                mcp_tool_description="Read file contents",
            )
        )

        # Get tool by ID
        tool = await MCPToolDAO.get_by_id(tool_id)

        # Get tools by client
        tools = await MCPToolDAO.get_by_client(client_id)

        # Update tool
        updated = await MCPToolDAO.update(
            MCPToolUpdate(id=tool_id, is_active=False)
        )

        # Delete tool
        success = await MCPToolDAO.delete(tool_id)
    """

    @staticmethod
    async def create(
        dto: MCPToolCreate,
        session: Optional[AsyncSession] = None,
    ) -> MCPTool:
        """Create a new MCP tool mapping.

        Args:
            dto: MCPToolCreate DTO with tool data.
            session: Optional async session for transaction control.

        Returns:
            MCPTool DTO with populated ID and generated fields.

        Raises:
            IntegrityError: If unique constraint violated or foreign key invalid.
        """
        entity = MCPToolEntity(
            mcp_client_id=dto.mcp_client_id,
            tool_id=dto.tool_id,
            mcp_tool_name=dto.mcp_tool_name,
            mcp_tool_description=dto.mcp_tool_description,
            mcp_tool_schema=dto.mcp_tool_schema,
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

        return MCPTool.model_validate(entity)

    @staticmethod
    async def get_by_id(
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> Optional[MCPTool]:
        """Retrieve an MCP tool by ID.

        Args:
            tool_id: UUID of the tool to retrieve.
            session: Optional async session for transaction control.

        Returns:
            MCPTool DTO if found, None otherwise.
        """
        async def _query(s: AsyncSession) -> Optional[MCPToolEntity]:
            result = await s.execute(
                select(MCPToolEntity).where(MCPToolEntity.id == tool_id)
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
        return MCPTool.model_validate(entity)

    @staticmethod
    async def get_by_client(
        mcp_client_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[MCPTool]:
        """Retrieve all tools for an MCP client.

        Args:
            mcp_client_id: UUID of the MCP client.
            session: Optional async session for transaction control.

        Returns:
            List of MCPTool DTOs.
        """
        async def _query(s: AsyncSession) -> List[MCPToolEntity]:
            result = await s.execute(
                select(MCPToolEntity).where(MCPToolEntity.mcp_client_id == mcp_client_id)
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

        return [MCPTool.model_validate(e) for e in entities]

    @staticmethod
    async def get_by_tool(
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[MCPTool]:
        """Retrieve all MCP tool mappings for an internal tool.

        Args:
            tool_id: UUID of the internal tool.
            session: Optional async session for transaction control.

        Returns:
            List of MCPTool DTOs.
        """
        async def _query(s: AsyncSession) -> List[MCPToolEntity]:
            result = await s.execute(
                select(MCPToolEntity).where(MCPToolEntity.tool_id == tool_id)
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

        return [MCPTool.model_validate(e) for e in entities]

    @staticmethod
    async def get_active_by_client(
        mcp_client_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> List[MCPTool]:
        """Retrieve all active tools for an MCP client.

        Args:
            mcp_client_id: UUID of the MCP client.
            session: Optional async session for transaction control.

        Returns:
            List of active MCPTool DTOs.
        """
        async def _query(s: AsyncSession) -> List[MCPToolEntity]:
            result = await s.execute(
                select(MCPToolEntity).where(
                    MCPToolEntity.mcp_client_id == mcp_client_id,
                    MCPToolEntity.is_active == True,
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

        return [MCPTool.model_validate(e) for e in entities]

    @staticmethod
    async def update(
        dto: MCPToolUpdate,
        session: Optional[AsyncSession] = None,
    ) -> Optional[MCPTool]:
        """Update an existing MCP tool.

        Only updates fields that are provided in the DTO.
        Automatically updates the updated_at timestamp.

        Args:
            dto: MCPToolUpdate DTO with fields to update (ID required).
            session: Optional async session for transaction control.

        Returns:
            Updated MCPTool DTO if entity exists, None otherwise.

        Raises:
            IntegrityError: If constraint violated.
        """
        async def _update(s: AsyncSession) -> Optional[MCPToolEntity]:
            # Fetch existing entity
            entity = await s.get(MCPToolEntity, dto.id)
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
        return MCPTool.model_validate(entity)

    @staticmethod
    async def delete(
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Delete an MCP tool by ID.

        Args:
            tool_id: UUID of the tool to delete.
            session: Optional async session for transaction control.

        Returns:
            True if deleted, False if not found.
        """
        async def _delete(s: AsyncSession) -> bool:
            stmt = delete(MCPToolEntity).where(MCPToolEntity.id == tool_id)
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
        """Check if an MCP tool exists.

        Args:
            tool_id: UUID of the tool to check.
            session: Optional async session for transaction control.

        Returns:
            True if tool exists, False otherwise.
        """
        async def _query(s: AsyncSession) -> bool:
            result = await s.execute(
                select(MCPToolEntity.id).where(MCPToolEntity.id == tool_id)
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
        """Count total number of MCP tools.

        Args:
            session: Optional async session for transaction control.

        Returns:
            Total count of MCP tools in table.
        """
        async def _query(s: AsyncSession) -> int:
            result = await s.execute(
                select(func.count()).select_from(MCPToolEntity)
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
    async def increment_invocation(
        tool_id: UUID,
        session: Optional[AsyncSession] = None,
    ) -> bool:
        """Increment the invocation count for an MCP tool.

        Also updates the last_invoked_at timestamp.

        Args:
            tool_id: UUID of the tool to update.
            session: Optional async session for transaction control.

        Returns:
            True if updated, False if not found.
        """
        async def _update(s: AsyncSession) -> bool:
            from datetime import datetime, timezone
            stmt = (
                update(MCPToolEntity)
                .where(MCPToolEntity.id == tool_id)
                .values(
                    invocation_count=MCPToolEntity.invocation_count + 1,
                    last_invoked_at=datetime.now(timezone.utc),
                )
            )
            result = await s.execute(stmt)
            await s.commit()
            return result.rowcount > 0

        if session is not None:
            return await _update(session)
        else:
            from db import create_engine, AsyncSession, async_sessionmaker
            engine = create_engine()
            async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            async with async_session() as s:
                success = await _update(s)
            await engine.dispose()
            return success
