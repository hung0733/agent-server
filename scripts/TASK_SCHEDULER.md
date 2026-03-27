# Task Scheduler 功能說明

## 概述

Task Scheduler 係一個後台服務，負責：
1. 定期掃描到期嘅排程任務
2. 檢查任務依賴關係
3. 將任務加入執行隊列
4. 執行任務並記錄結果
5. 計算下次執行時間

## 新增功能

### 1. Task Queue 整合

所有排程任務而家會先加入 `task_queue` 表，提供：
- ✅ 優先級排序
- ✅ 重試機制
- ✅ 執行狀態追蹤
- ✅ 結果記錄

#### Task Queue Schema

```sql
CREATE TABLE task_queue (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id),
    status VARCHAR(50) NOT NULL,  -- pending, running, completed, failed, cancelled
    priority INTEGER DEFAULT 0,
    queued_at TIMESTAMP WITH TIME ZONE NOT NULL,
    scheduled_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    claimed_by UUID REFERENCES agent_instances(id),
    claimed_at TIMESTAMP WITH TIME ZONE,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    error_message TEXT,
    result_json JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);
```

### 2. Task Dependencies 支援

而家可以設定任務之間嘅依賴關係：
- ✅ Sequential dependencies（順序依賴）
- ✅ Parallel dependencies（平行依賴）
- ✅ Conditional dependencies（條件依賴）

#### Task Dependencies Schema

```sql
CREATE TABLE task_dependencies (
    id UUID PRIMARY KEY,
    parent_task_id UUID NOT NULL REFERENCES tasks(id),
    child_task_id UUID NOT NULL REFERENCES tasks(id),
    dependency_type VARCHAR(50) NOT NULL DEFAULT 'sequential',
    condition_json JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    UNIQUE(parent_task_id, child_task_id),
    CHECK(parent_task_id != child_task_id)
);
```

#### 使用範例

```python
from db.dao.task_dependency_dao import TaskDependencyDAO
from db.dto.task_dependency_dto import TaskDependencyCreate

# 建立順序依賴：child_task 必須等 parent_task 完成
dependency = await TaskDependencyDAO.create(
    TaskDependencyCreate(
        parent_task_id=parent_task_id,
        child_task_id=child_task_id,
        dependency_type="sequential",
    )
)

# 檢查任務是否可以執行（所有依賴都已完成）
can_run = await TaskDependencyDAO.are_dependencies_met(task_id)
```

### 3. Tool Calls 記錄

`tool_calls` 表記錄所有工具調用：
- ✅ 輸入/輸出記錄
- ✅ 執行時間統計
- ✅ 錯誤追蹤

#### Tool Calls Schema

```sql
CREATE TABLE tool_calls (
    id UUID PRIMARY KEY,
    task_id UUID NOT NULL REFERENCES tasks(id),
    tool_id UUID NOT NULL REFERENCES tools(id),
    tool_version_id UUID REFERENCES tool_versions(id),
    input JSONB,
    output JSONB,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);
```

## Scheduler 執行流程

```
1. 掃描到期排程 (task_schedules WHERE next_run_at <= NOW())
   ↓
2. 為每個排程創建執行實例 (tasks table)
   ↓
3. 檢查任務依賴 (task_dependencies)
   ├─ 依賴未滿足 → 延遲 5 分鐘重試
   └─ 依賴已滿足 → 繼續
       ↓
4. 加入任務隊列 (task_queue)
   ↓
5. 執行任務
   ├─ 更新狀態為 running
   ├─ 調用 TaskExecutor
   ├─ 記錄 tool_calls (如有)
   └─ 更新狀態為 completed/failed
       ↓
6. 計算下次執行時間
   ├─ once → NULL (不再執行)
   ├─ cron → croniter 計算
   └─ interval → 加上時間間隔
       ↓
7. 更新排程 (task_schedules.next_run_at)
```

## API 使用

### TaskQueueDAO

```python
from db.dao.task_queue_dao import TaskQueueDAO
from db.dto.task_queue_dto import TaskQueueCreate, TaskQueueUpdate

# 建立隊列項目
queue_entry = await TaskQueueDAO.create(
    TaskQueueCreate(
        task_id=task_id,
        status="pending",
        priority=10,
        scheduled_at=datetime.now(timezone.utc),
    )
)

# 更新狀態
await TaskQueueDAO.update(
    TaskQueueUpdate(
        id=queue_entry.id,
        status="running",
        started_at=datetime.now(timezone.utc),
    )
)

# 查詢特定任務嘅隊列項目
entries = await TaskQueueDAO.get_by_task_id(task_id)

# 查詢被某個 agent 認領嘅任務
claimed = await TaskQueueDAO.get_by_claimed_by(agent_id)
```

### TaskDependencyDAO

```python
from db.dao.task_dependency_dao import TaskDependencyDAO
from db.dto.task_dependency_dto import TaskDependencyCreate

# 建立依賴
dependency = await TaskDependencyDAO.create(
    TaskDependencyCreate(
        parent_task_id=task_a_id,
        child_task_id=task_b_id,
        dependency_type="sequential",
    )
)

# 查詢所有子任務
children = await TaskDependencyDAO.get_by_parent_task(task_a_id)

# 查詢所有父任務
parents = await TaskDependencyDAO.get_by_child_task(task_b_id)

# 檢查依賴是否已滿足
can_run = await TaskDependencyDAO.are_dependencies_met(task_id)
if can_run:
    print("所有依賴已完成，可以執行！")
else:
    print("仍有依賴未完成，需要等待")
```

## 配置

環境變數：
```bash
# Scheduler 掃描間隔（秒）
SCHEDULER_INTERVAL_SECONDS=60

# 是否啟用 Scheduler
SCHEDULER_ENABLED=true
```

## 查詢範例

### 查看隊列狀態

```sql
-- 查看待處理任務
SELECT * FROM task_queue
WHERE status = 'pending'
ORDER BY priority DESC, scheduled_at ASC
LIMIT 10;

-- 查看正在執行嘅任務
SELECT
    tq.*,
    t.task_type,
    ai.name as agent_name
FROM task_queue tq
JOIN tasks t ON tq.task_id = t.id
LEFT JOIN agent_instances ai ON tq.claimed_by = ai.id
WHERE tq.status = 'running';

-- 查看失敗任務
SELECT
    tq.id,
    tq.task_id,
    tq.retry_count,
    tq.max_retries,
    tq.error_message,
    t.task_type
FROM task_queue tq
JOIN tasks t ON tq.task_id = t.id
WHERE tq.status = 'failed';
```

### 查看任務依賴

```sql
-- 查看任務依賴鏈
SELECT
    td.id,
    pt.id as parent_task_id,
    pt.task_type as parent_type,
    pt.status as parent_status,
    ct.id as child_task_id,
    ct.task_type as child_type,
    ct.status as child_status,
    td.dependency_type
FROM task_dependencies td
JOIN tasks pt ON td.parent_task_id = pt.id
JOIN tasks ct ON td.child_task_id = ct.id
ORDER BY td.created_at DESC;

-- 查找所有等待中嘅子任務
SELECT DISTINCT
    ct.*
FROM task_dependencies td
JOIN tasks pt ON td.parent_task_id = pt.id
JOIN tasks ct ON td.child_task_id = ct.id
WHERE pt.status != 'completed'
AND ct.status = 'pending';
```

### 查看工具調用統計

```sql
-- 查看工具調用次數統計
SELECT
    t.name as tool_name,
    COUNT(*) as total_calls,
    COUNT(CASE WHEN tc.status = 'completed' THEN 1 END) as success_count,
    COUNT(CASE WHEN tc.status = 'failed' THEN 1 END) as fail_count,
    AVG(tc.duration_ms) as avg_duration_ms
FROM tool_calls tc
JOIN tools t ON tc.tool_id = t.id
GROUP BY t.id, t.name
ORDER BY total_calls DESC;

-- 查看最近嘅工具調用
SELECT
    tc.*,
    t.name as tool_name,
    tasks.task_type
FROM tool_calls tc
JOIN tools t ON tc.tool_id = t.id
JOIN tasks ON tc.task_id = tasks.id
ORDER BY tc.created_at DESC
LIMIT 20;
```

## 故障排除

### 任務一直 pending

**可能原因**:
1. 依賴未滿足
2. Scheduler 未啟動
3. `next_run_at` 時間未到

**檢查方法**:
```sql
-- 檢查任務依賴
SELECT * FROM task_dependencies
WHERE child_task_id = 'your-task-id';

-- 檢查排程時間
SELECT * FROM task_schedules
WHERE task_template_id = 'your-template-id';
```

### 任務執行失敗

**檢查步驟**:
1. 查看 `task_queue.error_message`
2. 查看 `tasks.error_message`
3. 檢查 application logs
4. 檢查 `tool_calls` 表（如果有工具調用）

```sql
-- 查看失敗詳情
SELECT
    tq.error_message as queue_error,
    t.error_message as task_error,
    t.result
FROM task_queue tq
JOIN tasks t ON tq.task_id = t.id
WHERE tq.status = 'failed';
```

### 依賴循環檢測

Task dependencies 不允許循環依賴（A → B → A）。

**檢測方法**:
```python
from db.dao.task_dependency_dao import TaskDependencyDAO

# 嘗試建立依賴時會自動檢查 self-reference
# 但要檢測深層循環需要額外邏輯
```

## 最佳實踐

1. **設定合理嘅優先級**
   - 緊急任務: priority >= 10
   - 一般任務: priority = 5
   - 低優先級: priority = 0

2. **使用依賴而非輪詢**
   - ❌ 不要用 cron 每分鐘檢查前置任務狀態
   - ✅ 使用 task_dependencies 建立依賴關係

3. **設定適當嘅重試次數**
   - 網絡請求: max_retries = 3
   - 資料處理: max_retries = 1
   - 關鍵任務: max_retries = 5

4. **監控隊列長度**
   ```sql
   SELECT status, COUNT(*)
   FROM task_queue
   GROUP BY status;
   ```

## 未來擴展

1. **Dead Letter Queue (DLQ)** - 已有 table，需要整合
2. **分散式執行** - 多個 scheduler instances
3. **優先級動態調整** - 根據等待時間提升優先級
4. **依賴條件評估** - 支援 condition_json 條件判斷
5. **工具調用重試** - 針對個別工具嘅重試邏輯

## 參考資料

- [Task Scheduler 源碼](../src/scheduler/task_scheduler.py)
- [Task Queue DAO](../src/db/dao/task_queue_dao.py)
- [Task Dependency DAO](../src/db/dao/task_dependency_dao.py)
- [Database Schema](../alembic/versions/)
