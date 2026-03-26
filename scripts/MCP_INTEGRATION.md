# MCP (Model Context Protocol) Integration

本文檔說明如何整合 MCP servers 到 Agent Server。

## 概述

MCP 整合允許你：
1. 連接到外部 MCP servers
2. 自動發現並載入 MCP 提供嘅工具
3. 將 MCP tools 保存到資料庫
4. 讓 agents 使用 MCP tools

## 資料庫結構

### Tables

#### `mcp_clients`
儲存 MCP server 連接資訊

| 欄位 | 類型 | 描述 |
|------|------|------|
| `id` | UUID | Primary key |
| `user_id` | UUID | 擁有者用戶 ID |
| `name` | Text | MCP client 名稱 |
| `description` | Text | 描述 |
| `protocol` | Text | 協議 (`http`, `websocket`) |
| `base_url` | Text | MCP server URL |
| `api_key_encrypted` | Text | 加密嘅 API key |
| `headers` | JSONB | 自定義 HTTP headers |
| `auth_type` | Text | 認證類型 (`none`, `api_key`, `bearer`, `basic`, `oauth2`) |
| `auth_config` | JSONB | 認證配置 |
| `status` | Text | 連接狀態 (`connected`, `disconnected`, `error`) |
| `last_connected_at` | Timestamp | 最後連接時間 |
| `last_error` | Text | 最後錯誤訊息 |
| `client_metadata` | JSONB | 額外元數據 |
| `is_active` | Boolean | 是否啟用 |

#### `mcp_tools`
儲存 MCP tool 映射關係

| 欄位 | 類型 | 描述 |
|------|------|------|
| `id` | UUID | Primary key |
| `mcp_client_id` | UUID | MCP client 外鍵 |
| `tool_id` | UUID | 內部 tool 外鍵 |
| `mcp_tool_name` | Text | MCP tool 原始名稱 |
| `mcp_tool_description` | Text | Tool 描述 |
| `mcp_tool_schema` | JSONB | Tool input schema |
| `is_active` | Boolean | 是否啟用 |
| `last_invoked_at` | Timestamp | 最後調用時間 |
| `invocation_count` | Integer | 調用次數 |

## 使用方法

### 1. 啟動 MCP Server

以 filesystem MCP server 為例：

```bash
# 安裝 filesystem MCP server
npm install -g @modelcontextprotocol/server-filesystem

# 啟動 server（端口 3000）
npx @modelcontextprotocol/server-filesystem --port 3000
```

### 2. 運行測試 Script

```bash
# 確保已啟動 MCP server
python scripts/test_mcp_filesystem.py
```

測試 script 會：
1. 連接到 MCP server
2. 發現所有可用嘅 tools
3. 保存 MCP client 到 `mcp_clients` 表
4. 保存所有 tools 到 `tools` 表
5. 建立 MCP tool 映射到 `mcp_tools` 表

### 3. 編程使用

```python
from mcp.mcp_connector import MCPConnector
from uuid import UUID

# 連接並發現工具
result = await MCPConnector.connect_and_discover(
    base_url="http://localhost:3000",
    user_id=UUID("your-user-id"),
    name="My MCP Server",
    description="Description of the server",
    protocol="http",
    auth_type="none",  # or "api_key", "bearer", etc.
    api_key=None,  # Set if needed
    headers=None,  # Custom headers if needed
)

# 檢查結果
print(f"Status: {result['status']}")
print(f"Client ID: {result['client_id']}")
print(f"Tools discovered: {result['tools_discovered']}")
print(f"Tools added: {result['tools_added']}")
```

### 4. 查詢數據

```sql
-- 查詢所有 MCP clients
SELECT * FROM mcp_clients;

-- 查詢特定 client 嘅所有 tools
SELECT
    mt.mcp_tool_name,
    mt.mcp_tool_description,
    t.name as internal_tool_name,
    mt.invocation_count,
    mt.last_invoked_at
FROM mcp_tools mt
JOIN tools t ON mt.tool_id = t.id
WHERE mt.mcp_client_id = 'your-client-id';

-- 查詢最常用嘅 MCP tools
SELECT
    mcp_tool_name,
    invocation_count,
    last_invoked_at
FROM mcp_tools
ORDER BY invocation_count DESC
LIMIT 10;
```

## API 結構

### Entity Layer
- `src/db/entity/mcp_client_entity.py` - MCP Client SQLAlchemy model
- `src/db/entity/mcp_tool_entity.py` - MCP Tool SQLAlchemy model

### DTO Layer
- `src/db/dto/mcp_client_dto.py` - MCP Client Pydantic DTOs
- `src/db/dto/mcp_tool_dto.py` - MCP Tool Pydantic DTOs

### DAO Layer
- `src/db/dao/mcp_client_dao.py` - MCP Client database operations
- `src/db/dao/mcp_tool_dao.py` - MCP Tool database operations

### Integration Layer
- `src/mcp/mcp_connector.py` - MCP server connector

## 常見 MCP Servers

### Filesystem Server
```bash
npm install -g @modelcontextprotocol/server-filesystem
npx @modelcontextprotocol/server-filesystem --port 3000
```

提供工具：
- `read_file` - 讀取檔案內容
- `write_file` - 寫入檔案
- `list_directory` - 列出目錄
- `create_directory` - 建立目錄
- 等等...

### Database Server
```bash
npm install -g @modelcontextprotocol/server-postgres
npx @modelcontextprotocol/server-postgres --connection-string "postgresql://..." --port 3001
```

提供工具：
- `query` - 執行 SQL 查詢
- `describe_table` - 描述資料表結構
- 等等...

### GitHub Server
```bash
npm install -g @modelcontextprotocol/server-github
npx @modelcontextprotocol/server-github --token "ghp_..." --port 3002
```

提供工具：
- `create_issue` - 建立 issue
- `list_pull_requests` - 列出 PRs
- `search_code` - 搜尋代碼
- 等等...

## 注意事項

1. **安全性**
   - API keys 會使用 `CryptoManager` 加密後存儲
   - 確保 `.env` 文件嘅 `CRYPTO_KEY` 設定正確

2. **錯誤處理**
   - 連接失敗時會保存 error 狀態到資料庫
   - 檢查 `mcp_clients.last_error` 欄位查看錯誤訊息

3. **工具去重**
   - 相同名稱嘅工具只會在 `tools` 表創建一次
   - `mcp_tools` 表會記錄映射關係

4. **連接狀態**
   - `connected` - 成功連接並載入工具
   - `disconnected` - 未連接或已斷開
   - `error` - 連接失敗

## 故障排除

### 連接失敗

```
❌ MCP 連接失敗: Connection refused
```

**解決方法**:
1. 確認 MCP server 正在運行
2. 檢查 `base_url` 是否正確
3. 檢查防火牆設定

### 工具發現失敗

```
❌ 無效的 MCP 回應格式
```

**解決方法**:
1. 確認 MCP server 符合 MCP protocol 規範
2. 檢查 server 嘅 `/mcp/v1/tools` endpoint
3. 查看 server logs 了解詳情

### 資料庫錯誤

```
IntegrityError: duplicate key value violates unique constraint
```

**解決方法**:
1. 相同 `mcp_client_id` 同 `tool_id` 組合已存在
2. 檢查 `mcp_tools` 表嘅 unique constraint
3. 先刪除舊記錄或更新現有記錄

## 未來擴展

1. **WebSocket Support** - 支援 WebSocket 協議嘅 MCP servers
2. **Tool Invocation** - 實現 MCP tool 嘅實際調用
3. **Auto Sync** - 定期同步 MCP server 嘅 tools
4. **Health Check** - 定期檢查 MCP client 嘅連接狀態
5. **Rate Limiting** - 限制 MCP tool 嘅調用頻率

## 參考資料

- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [MCP Official Servers](https://github.com/modelcontextprotocol/servers)
