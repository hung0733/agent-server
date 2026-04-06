# DB Connection Storm Design

## Context

`review_ltm()` 在處理每個 chunk 時都會建立新的 `MultiAgentMemorySystem`，而 `MultiAgentMemorySystem.initialize()` 會建立新的 `asyncpg` pool。與此同時，多個 DAO 在沒有傳入 session 時，會各自 `create_engine()`、建立 session、完成後 `dispose()`。在 scheduler、LTM 摘要、背景資料更新同時進行時，系統會短時間內建立大量 PostgreSQL 連線，導致廣泛 `asyncpg TimeoutError`。

另外，當 `MultiAgentMemorySystem.initialize()` 在建立 pool 前失敗時，`close()` 仍會存取未初始化的 `pg_pool`，產生次生錯誤，遮蓋原始問題。

## Goals

- 消除 `review_ltm()` 每個 chunk 重建 pool 的行為。
- 把 DAO 的預設資料庫存取改為共享 `AsyncEngine` 與共享 `async_sessionmaker`。
- 移除 `MultiAgentMemorySystem.close()` 對未初始化屬性的依賴。
- 降低 LTM 摘要流程中的額外背景 DB 壓力。

## Non-Goals

- 不改變 scheduler、DAO、LTM 對外 API。
- 不處理與今次 PostgreSQL timeout 無直接關係的 WhatsApp / Engine.IO 連線問題。
- 不進行全專案資料層重寫，只修正本次連線風暴涉及的建立與生命週期模式。

## Approach Options

### Option 1: LTM-only hotfix

只修 `MultiAgentMemorySystem` 與 `review_ltm()`，避免每 chunk 建 pool。

優點：改動最少。
缺點：DAO 仍然會大量新建 engine，scheduler 在壓力下仍可觸發相同 timeout。

### Option 2: Recommended layered fix

同時修正兩層：

1. `review_ltm()` 內重用單一 `MultiAgentMemorySystem`。
2. `db` 模組提供共享 engine 與 session factory，DAO 改為重用。

優點：直接命中根因，並改善 scheduler / DAO 全系統連線模式。
缺點：需要修改多個 DAO 檔案，但變更模式一致。

### Option 3: Full data-layer refactor

全面重寫 DAO / session 注入方式。

優點：長遠最整齊。
缺點：範圍過大，與當前事故修復不匹配。

## Chosen Design

採用 Option 2。

### 1. Shared DB Infrastructure

在 `src/db/__init__.py` 提供：

- module-level shared `AsyncEngine`
- module-level shared `async_sessionmaker`
- 取得 shared engine / session factory 的 helper

現有 `create_engine()` 保留，但新增預設共享路徑，讓 DAO 在未傳入 session 時不再反覆建立和銷毀 engine。

### 2. DAO Access Pattern

更新今次錯誤路徑直接涉及的 DAO，例如：

- `TaskDAO`
- `TaskQueueDAO`
- `TaskScheduleDAO`
- `AgentMessageDAO`
- `AgentInstanceDAO`
- `LLMLevelEndpointDAO`

變更方式：

- 若呼叫端已提供 session，沿用原邏輯。
- 若未提供 session，改用 shared session factory 建立短生命週期 session。
- 不再在每次 DAO 呼叫後 `engine.dispose()`。

這樣保留現有 API，同時消除 connection churn。

### 3. LTM Lifecycle

在 `MultiAgentMemorySystem.__init__()` 中先將以下屬性設為 `None`：

- `pg_pool`
- `qdrant_client`
- `pg_store`
- 其他在 `initialize()` 後才存在的資源

`close()` 會檢查資源是否存在才清理，避免在初始化失敗時再拋出次生錯誤。

在 `review_ltm()` 中，整次 agent review 共用同一個 `MultiAgentMemorySystem` 實例。`_summary_ltm()` 改為接收已初始化的 LTM 實例，而不是自行建立與關閉。

### 4. Summarized Flag Update Pressure

`_batch_update_summarized()` 不再透過 `Tools.start_async_task()` 無限制背景執行。改為在 chunk 完成後直接 await 同步更新，確保：

- 不額外製造併發 DB 壓力
- 錯誤會在主流程內可見
- 摘要完成與標記完成的語義一致

### 5. Failure Handling

若某個 chunk 摘要失敗：

- 記錄錯誤並返回 `False`
- 不標記該批訊息為 `is_summarized=True`
- 其他 chunks 維持現有流程繼續處理

若 shared DB engine 初始化失敗，錯誤直接向上拋出，不再加入額外 cleanup noise。

## Data Flow

### Before

1. `review_ltm()` 逐 chunk 呼叫 `_summary_ltm()`
2. `_summary_ltm()` 建立新的 `MultiAgentMemorySystem`
3. `initialize()` 建立新的 `asyncpg` pool
4. chunk 完成後背景啟動 `batch_update_is_summarized()`
5. DAO 個別再建立自己的 engine / session

### After

1. `review_ltm()` 建立一次 `MultiAgentMemorySystem`
2. 所有 chunks 重用同一個 LTM 實例與同一個 pool
3. chunk 完成後同步更新 `is_summarized`
4. DAO 透過 shared engine / shared session factory 存取資料庫

## Testing Strategy

### Static verification

- 搜尋確認今次修改的 DAO 不再包含 `create_engine()` + `engine.dispose()` 的 per-call 模式。
- 搜尋確認 `review_ltm()` 不再為每個 chunk 建立 `MultiAgentMemorySystem`。

### Targeted runtime verification

- 在安全前提下執行與 LTM / scheduler 相關的單元測試，若有現成測試可用則優先使用。
- 若缺少直接測試，至少執行 import / compilation level verification。

### Expected outcomes

- 不再出現 `'MultiAgentMemorySystem' object has no attribute 'pg_pool'`
- `review_ltm()` 單次執行期間只初始化一次 LTM system
- DAO 預設路徑不再反覆建立 engine

## Risks And Mitigations

### Risk: Shared engine changes connection lifetime semantics

Mitigation: 保留 DAO 傳入 session 的現有模式；只改未傳入 session 的 fallback 路徑。

### Risk: Synchronous summarized update lowers throughput

Mitigation: 今次優先處理穩定性。若之後需要吞吐量，再引入受控 queue / semaphore，而唔係無限制背景 task。

### Risk: 有其他 DAO 仍然保留舊模式

Mitigation: 先修直接出現在 stack trace 的 DAO；保留 shared session helper，方便後續逐步擴展。
