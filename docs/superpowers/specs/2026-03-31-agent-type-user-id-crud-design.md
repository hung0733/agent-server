# Agent Type：加 user_id 及 CRUD UI 設計

**日期**：2026-03-31

## 概述

在 `agent_types` 表加入 `user_id`，實現多租戶隔離（每個用戶只能看到和管理自己的 agent type）。同時新增後端 CRUD API 端點及前端管理 UI，取代現有的佔位符。

---

## 1. 資料庫

### Migration

- 在 `agent_types` 加欄位：`user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE`
- 加索引：`idx_agent_types_user_id`
- 移除舊的 `UNIQUE(name)` 約束
- 新增 `UNIQUE(user_id, name)` 複合唯一約束（允許不同用戶使用相同類型名稱）

---

## 2. 後端

### Entity（`src/db/entity/agent_entity.py`）

`AgentType` 加：
```python
user_id: Mapped[UUID] = mapped_column(
    PostgreSQLUUID(as_uuid=True),
    ForeignKey("users.id", ondelete="CASCADE"),
    nullable=False,
    index=True,
)
```
加 `idx_agent_types_user_id` 索引。

### DTOs（`src/db/dto/agent_dto.py`）

- `AgentTypeBase` 加 `user_id: UUID`
- `AgentTypeCreate` 繼承即可（無需額外變更）
- `AgentType`（完整 DTO）加 `user_id: UUID`
- `AgentTypeUpdate` 無需改動

### DAO（`src/db/dao/agent_type_dao.py`）

- `get_all()` 加 `user_id: Optional[UUID] = None` 參數，若提供則過濾
- `create()` 將 `user_id` 傳入 entity

### API 端點（`src/api/app.py`）

新增四個路由，全部需要認證：

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/dashboard/agent-types` | 列出該用戶的所有 agent type |
| POST | `/api/dashboard/agent-types` | 新增 agent type |
| PATCH | `/api/dashboard/agent-types/{id}` | 修改（驗證擁有者） |
| DELETE | `/api/dashboard/agent-types/{id}` | 刪除（驗證擁有者） |

**序列化格式**（JSON 回應）：
```json
{
  "id": "uuid",
  "name": "string",
  "description": "string | null",
  "isActive": true,
  "createdAt": "ISO8601"
}
```

列表端點回傳：`{ "agentTypes": [...] }`

---

## 3. 前端

### 類型定義（`frontend/src/types/dashboard.ts`）

```typescript
export interface AgentTypeItem {
  id: string;
  name: string;
  description: string | null;
  isActive: boolean;
  createdAt: string;
}

export interface AgentTypesPayload {
  agentTypes: AgentTypeItem[];
}
```

### API 函數（`frontend/src/api/dashboard.ts`）

```typescript
fetchAgentTypes(): Promise<AgentTypesPayload>
createAgentType(body): Promise<{ agentType: AgentTypeItem }>
updateAgentType(id, body): Promise<{ agentType: AgentTypeItem }>
deleteAgentType(id): Promise<{ deleted: boolean }>
```

### 元件：`AgentTypesTab.tsx`

- 表格顯示：名稱、描述、啟用狀態、操作（編輯、刪除）
- 頂部「+ 新增」按鈕
- 點擊新增或編輯開啟 modal 表單，欄位：名稱（必填）、描述（選填）、啟用（checkbox）
- 刪除時顯示確認提示
- `AgentsPage.tsx` 的 `agent-type` tab 改為渲染 `<AgentTypesTab />`

---

## 4. 錯誤處理

- 新增/編輯時若名稱已存在（同一用戶），API 回傳 409，前端顯示錯誤訊息
- 修改/刪除不存在或不屬於該用戶的 type 回傳 404

---

## 5. 測試

- 後端 unit tests：`AgentTypeDAO` 加 `user_id` 過濾的測試
- 後端 unit tests：新 API 端點的 CRUD 測試
- 前端：`AgentTypesTab` 的 render 及互動測試
