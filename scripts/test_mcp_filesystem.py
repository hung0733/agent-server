#!/usr/bin/env python3
"""
Test script for MCP Filesystem server integration.

This script demonstrates how to:
1. Connect to an MCP server (filesystem MCP server as example)
2. Discover available tools
3. Save MCP client and tools to database

Usage:
    python scripts/test_mcp_filesystem.py

Prerequisites:
    - Filesystem MCP server running (e.g., on http://localhost:3000)
    - Database migrations applied
    - Environment variables configured

Example MCP filesystem server:
    You can use @modelcontextprotocol/server-filesystem
    npm install -g @modelcontextprotocol/server-filesystem
    npx @modelcontextprotocol/server-filesystem --port 3000
"""
import asyncio
import sys
from pathlib import Path
from uuid import UUID

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.mcp_connector import MCPConnector
from db.dao.user_dao import UserDAO
from tools.db_pool import configure_pool
from i18n import _


async def main():
    """Main test function."""
    print("=" * 80)
    print("MCP Filesystem Server 測試")
    print("=" * 80)

    # 1. Initialize database connection pool
    print("\n📦 初始化資料庫連接池...")
    await configure_pool()
    print("✅ 資料庫連接池已初始化")

    # 2. Get or create test user
    print("\n👤 獲取測試用戶...")
    users = await UserDAO.get_all(limit=1)
    if not users:
        print("❌ 錯誤：找不到用戶，請先創建用戶")
        return

    user = users[0]
    user_id = user.id
    print(f"✅ 使用用戶: {user.username} (ID: {user_id})")

    # 3. Configure MCP server connection
    # NOTE: Change these settings to match your MCP server
    print("\n⚙️ 配置 MCP server 連接...")

    mcp_config = {
        "base_url": "http://localhost:3000",  # Change if your server runs elsewhere
        "user_id": user_id,
        "name": "Filesystem MCP Server",
        "description": "本地檔案系統 MCP server，提供檔案操作工具",
        "protocol": "http",
        "auth_type": "none",  # Change if your server requires auth
        "api_key": None,  # Set if auth_type is api_key or bearer
        "headers": None,  # Optional custom headers
    }

    print(f"  Base URL: {mcp_config['base_url']}")
    print(f"  Protocol: {mcp_config['protocol']}")
    print(f"  Auth Type: {mcp_config['auth_type']}")

    # 4. Connect and discover tools
    print(f"\n🔗 正在連接 MCP server: {mcp_config['base_url']}...")
    print("請確保 MCP server 正在運行！\n")

    try:
        result = await MCPConnector.connect_and_discover(**mcp_config)

        # 5. Display results
        print("\n" + "=" * 80)
        print("📊 連接結果")
        print("=" * 80)

        print(f"狀態: {result['status']}")
        print(f"Client ID: {result['client_id']}")
        print(f"發現工具數量: {result['tools_discovered']}")
        print(f"成功添加工具: {result['tools_added']}")

        if result['error']:
            print(f"\n❌ 錯誤: {result['error']}")

        if result['tools']:
            print(f"\n📋 工具列表 ({len(result['tools'])} 個):")
            print("-" * 80)
            for i, tool in enumerate(result['tools'], 1):
                print(f"\n{i}. {tool.get('name', 'Unknown')}")
                print(f"   描述: {tool.get('description', 'N/A')}")
                if 'inputSchema' in tool:
                    schema = tool['inputSchema']
                    if isinstance(schema, dict):
                        properties = schema.get('properties', {})
                        print(f"   參數: {list(properties.keys())}")

        print("\n" + "=" * 80)
        print("✅ 測試完成！")
        print("=" * 80)

        # 6. Verify data in database
        if result['client_id']:
            print(f"\n💾 資料已保存到資料庫:")
            print(f"   - mcp_clients 表: 1 條記錄 (ID: {result['client_id']})")
            print(f"   - mcp_tools 表: {result['tools_added']} 條記錄")
            print(f"   - tools 表: {result['tools_added']} 條記錄 (新增或已存在)")

            print(f"\n🔍 查詢數據:")
            print(f"   SELECT * FROM mcp_clients WHERE id = '{result['client_id']}';")
            print(f"   SELECT * FROM mcp_tools WHERE mcp_client_id = '{result['client_id']}';")

    except Exception as e:
        print(f"\n❌ 測試失敗: {e}")
        import traceback
        traceback.print_exc()
        return

    print("\n✨ 所有測試通過！")


if __name__ == "__main__":
    asyncio.run(main())
