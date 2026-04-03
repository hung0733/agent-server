# 路徑安全機制

## 概述

為了防止 agent 存取或修改其他用戶的檔案或系統檔案,本系統實作了基於 user sandbox 的路徑安全機制。每個 agent 只能在 `AGENT_HOME_DIR/{user_id}` 資料夾內自由修改檔案。

## 架構設計

### 1. 環境變數配置

在 `.env` 檔案中配置 agent home 目錄:

```bash
AGENT_HOME_DIR=/mnt/data/misc/agent-server/home/
```

### 2. 核心模組

#### `src/tools/path_security.py`

提供路徑安全驗證功能:

- `get_agent_home_dir()` - 獲取 agent home 目錄
- `get_user_sandbox_dir(user_id)` - 獲取特定用戶的 sandbox 目錄
- `validate_path_access(path, user_id)` - 驗證路徑是否在 sandbox 內
- `resolve_safe_path(path, user_id, base_dir)` - 安全解析路徑

#### `src/tools/tools.py`

在 `get_tools()` 函數中:
1. 從 `AgentInstanceDAO` 獲取 agent 的 `user_id`
2. 將 `user_id` 注入到 `merged_config` 中
3. 每個工具執行時可從 `_config` 獲取 `user_id`

#### `src/tools/system_tools.py`

所有檔案系統工具 (read, write, edit, grep, find, ls, exec, process) 都會:
1. 從 `_config` 獲取 `user_id`
2. 使用 `_resolve_path()` 驗證路徑
3. 如果路徑超出 sandbox,返回錯誤訊息

## 安全特性

### 1. 用戶隔離

每個用戶都有獨立的 sandbox 目錄:
- User A: `AGENT_HOME_DIR/user-a-uuid/`
- User B: `AGENT_HOME_DIR/user-b-uuid/`

User A 的 agent 無法存取 User B 的檔案。

### 2. 路徑遍歷防護

防止使用 `../` 等路徑遍歷技巧逃出 sandbox:

```python
# ❌ 被阻擋
read_impl("../../../etc/passwd", _config={"user_id": "xxx"})

# ✅ 允許
read_impl("data/file.txt", _config={"user_id": "xxx"})
```

### 3. 符號連結防護

符號連結會被解析,如果指向 sandbox 外部則被阻擋。

### 4. 絕對路徑驗證

即使提供絕對路徑,也必須在 sandbox 內:

```python
# ❌ 被阻擋
read_impl("/etc/passwd", _config={"user_id": "xxx"})

# ✅ 允許 (如果在 sandbox 內)
read_impl("/mnt/data/misc/agent-server/home/user-xxx/file.txt",
          _config={"user_id": "xxx"})
```

## 工具函數範例

### 讀取檔案

```python
# Agent 只能讀取自己 sandbox 內的檔案
result = await read_impl(
    path="data/input.txt",
    _config={"user_id": "abc123"}
)
```

如果嘗試存取 sandbox 外的檔案:
```
🚫 拒絕存取: 路徑 /etc/passwd 超出允許範圍 /mnt/data/misc/agent-server/home/abc123
```

### 執行命令

```python
# 命令的工作目錄也受到 sandbox 限制
result = await exec_impl(
    command="ls -la",
    cwd="projects/myapp",  # 解析為 sandbox/projects/myapp
    _config={"user_id": "abc123"}
)
```

## 向後兼容性

如果 `_config` 中沒有 `user_id`,系統會回退到傳統行為 (不進行安全檢查)。這確保了:
1. 現有的非 agent 工具調用仍然可以正常運作
2. 測試環境中可以選擇性地啟用/停用安全機制

## 測試

完整的單元測試位於 `tests/unit/test_path_security.py`:

```bash
pytest tests/unit/test_path_security.py -v
```

測試涵蓋:
- ✅ Sandbox 內的路徑存取
- ✅ Sandbox 外的路徑被阻擋
- ✅ 路徑遍歷攻擊防護
- ✅ 符號連結逃逸防護
- ✅ 多用戶隔離
- ✅ 相對/絕對路徑處理

## 未來改進

1. **審計日誌** - 記錄所有被阻擋的路徑存取嘗試
2. **配額管理** - 限制每個用戶的磁碟空間使用
3. **檔案類型限制** - 限制可執行檔案的建立
4. **讀寫權限細分** - 區分唯讀和可寫區域
