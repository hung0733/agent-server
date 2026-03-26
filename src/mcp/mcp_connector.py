# pyright: reportMissingImports=false
"""
MCP (Model Context Protocol) client connector.

This module provides tools to connect to MCP servers, discover tools,
and save them to the database.

Import path: src.mcp.mcp_connector
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

import httpx

from db.dao.mcp_client_dao import MCPClientDAO
from db.dao.mcp_tool_dao import MCPToolDAO
from db.dao.tool_dao import ToolDAO
from db.dto.mcp_client_dto import MCPClientCreate, MCPClientUpdate
from db.dto.mcp_tool_dto import MCPToolCreate
from db.dto.tool_dto import ToolCreate
from i18n import _

logger = logging.getLogger(__name__)


class MCPConnector:
    """MCP client connector for discovering and managing MCP tools.

    This class provides methods to:
    1. Connect to an MCP server
    2. Discover available tools
    3. Save MCP client and tools to database
    4. Map MCP tools to internal tools table
    """

    @staticmethod
    async def connect_and_discover(
        base_url: str,
        user_id: UUID,
        name: str,
        description: Optional[str] = None,
        protocol: str = "http",
        auth_type: str = "none",
        api_key: Optional[str] = None,
        headers: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Connect to an MCP server and discover available tools.

        Args:
            base_url: MCP server base URL (e.g., "http://localhost:3000")
            user_id: UUID of the user creating this connection
            name: Human-readable name for this MCP client
            description: Optional description
            protocol: Protocol type ("http" or "websocket")
            auth_type: Authentication type ("none", "api_key", "bearer", etc.)
            api_key: Optional API key for authentication
            headers: Optional custom HTTP headers

        Returns:
            Dictionary with:
            {
                "client_id": UUID,
                "tools_discovered": int,
                "tools_added": int,
                "tools": List[dict],
                "status": str,
                "error": Optional[str],
            }

        Raises:
            httpx.HTTPError: If connection fails
            ValueError: If invalid parameters provided
        """
        logger.info(
            _("🔗 正在連接 MCP server: %s (名稱: %s)"),
            base_url,
            name,
        )

        result = {
            "client_id": None,
            "tools_discovered": 0,
            "tools_added": 0,
            "tools": [],
            "status": "error",
            "error": None,
        }

        try:
            # 1. Test connection and discover tools
            tools_list = await MCPConnector._discover_tools(
                base_url=base_url,
                auth_type=auth_type,
                api_key=api_key,
                headers=headers,
            )

            result["tools_discovered"] = len(tools_list)
            result["tools"] = tools_list

            logger.info(
                _("✅ 成功發現 %d 個工具"),
                len(tools_list),
            )

            # 2. Save MCP client to database
            from db.crypto import CryptoManager

            api_key_encrypted = None
            if api_key:
                api_key_encrypted = CryptoManager().encrypt(api_key)

            mcp_client_dto = await MCPClientDAO.create(
                MCPClientCreate(
                    user_id=user_id,
                    name=name,
                    description=description,
                    protocol=protocol,
                    base_url=base_url,
                    api_key_encrypted=api_key_encrypted,
                    headers=headers or {},
                    auth_type=auth_type,
                    auth_config={},
                    status="connected",
                    last_error=None,
                    client_metadata={
                        "tools_count": len(tools_list),
                    },
                    is_active=True,
                )
            )

            result["client_id"] = mcp_client_dto.id
            logger.info(
                _("✅ MCP client 已保存到資料庫: %s"),
                mcp_client_dto.id,
            )

            # 3. Add tools to database
            tools_added = 0
            for tool_info in tools_list:
                try:
                    # Create or get tool in tools table
                    tool_name = tool_info.get("name", "")
                    tool_description = tool_info.get("description", "")
                    tool_schema = tool_info.get("inputSchema", {})

                    # Check if tool already exists
                    existing_tool = await ToolDAO.get_by_name(tool_name)

                    if existing_tool:
                        tool_dto = existing_tool
                        logger.debug(
                            _("工具已存在: %s (ID: %s)"),
                            tool_name,
                            tool_dto.id,
                        )
                    else:
                        # Create new tool
                        tool_dto = await ToolDAO.create(
                            ToolCreate(
                                name=tool_name,
                                description=tool_description,
                                is_active=True,
                            )
                        )
                        logger.debug(
                            _("✅ 新工具已創建: %s (ID: %s)"),
                            tool_name,
                            tool_dto.id,
                        )

                    # Create MCP tool mapping
                    mcp_tool_dto = await MCPToolDAO.create(
                        MCPToolCreate(
                            mcp_client_id=mcp_client_dto.id,
                            tool_id=tool_dto.id,
                            mcp_tool_name=tool_name,
                            mcp_tool_description=tool_description,
                            mcp_tool_schema=tool_schema,
                            is_active=True,
                        )
                    )

                    tools_added += 1
                    logger.debug(
                        _("✅ MCP 工具映射已創建: %s"),
                        mcp_tool_dto.id,
                    )

                except Exception as tool_error:
                    logger.error(
                        _("⚠️ 添加工具失敗: %s - %s"),
                        tool_info.get("name", "unknown"),
                        str(tool_error),
                        exc_info=True,
                    )
                    continue

            result["tools_added"] = tools_added
            result["status"] = "connected"

            logger.info(
                _("🎉 MCP 連接完成: %d/%d 工具已添加"),
                tools_added,
                len(tools_list),
            )

            return result

        except Exception as e:
            error_msg = str(e)
            result["error"] = error_msg
            result["status"] = "error"

            logger.error(
                _("❌ MCP 連接失敗: %s"),
                error_msg,
                exc_info=True,
            )

            # Try to save client with error status
            if result["client_id"] is None:
                try:
                    mcp_client_dto = await MCPClientDAO.create(
                        MCPClientCreate(
                            user_id=user_id,
                            name=name,
                            description=description,
                            protocol=protocol,
                            base_url=base_url,
                            auth_type=auth_type,
                            status="error",
                            last_error=error_msg[:500],
                            is_active=False,
                        )
                    )
                    result["client_id"] = mcp_client_dto.id
                except Exception:
                    pass

            return result

    @staticmethod
    async def _discover_tools(
        base_url: str,
        auth_type: str = "none",
        api_key: Optional[str] = None,
        headers: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Discover tools from MCP server.

        Args:
            base_url: MCP server base URL
            auth_type: Authentication type
            api_key: Optional API key
            headers: Optional custom headers

        Returns:
            List of tool definitions from MCP server

        Raises:
            httpx.HTTPError: If request fails
        """
        # Prepare headers
        request_headers = headers or {}

        if auth_type == "api_key" and api_key:
            request_headers["X-API-Key"] = api_key
        elif auth_type == "bearer" and api_key:
            request_headers["Authorization"] = f"Bearer {api_key}"

        # Make request to MCP server's tools endpoint
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Try standard MCP endpoint
            url = f"{base_url.rstrip('/')}/mcp/v1/tools"

            logger.debug(_("正在發送請求到: %s"), url)

            response = await client.get(url, headers=request_headers)
            response.raise_for_status()

            data = response.json()

            # Extract tools from response
            # MCP spec: response should have "tools" array
            if isinstance(data, dict) and "tools" in data:
                tools = data["tools"]
            elif isinstance(data, list):
                tools = data
            else:
                raise ValueError(_("無效的 MCP 回應格式"))

            logger.debug(
                _("✅ 發現 %d 個工具"),
                len(tools),
            )

            return tools

    @staticmethod
    async def update_client_status(
        client_id: UUID,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Update MCP client connection status.

        Args:
            client_id: MCP client UUID
            status: New status ("connected", "disconnected", "error")
            error: Optional error message
        """
        from datetime import datetime, timezone

        await MCPClientDAO.update(
            MCPClientUpdate(
                id=client_id,
                status=status,
                last_error=error,
                last_connected_at=datetime.now(timezone.utc) if status == "connected" else None,
            )
        )

        logger.info(
            _("MCP client %s 狀態已更新: %s"),
            client_id,
            status,
        )
