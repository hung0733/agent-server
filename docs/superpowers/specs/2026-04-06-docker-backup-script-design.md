# Docker Backup Script Design

## Goal

將 `scripts/backup_production_data.py` 標準化為使用 Docker PostgreSQL image 執行 `pg_dump`，避免本機 `pg_dump` 與資料庫 server major version 不一致而令備份失敗。

## Scope

- 修改 `scripts/backup_production_data.py`
- 保留現有 `.env` / `POSTGRES_*` 設定方式
- 備份檔繼續輸出到 `backups/`
- 補單元測試覆蓋 Docker command 組裝與錯誤處理

## Proposed Behavior

- script 讀取 `POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB`
- script 用 Docker 執行 `postgres:17` image 內嘅 `pg_dump`
- 將 repo `backups/` 掛載到 container 內 `/backups`
- 備份檔名維持現有 timestamp 命名格式
- 成功時輸出 backup path
- 失敗時回傳清晰錯誤，包括：
  - Docker 未安裝
  - Docker command 執行失敗

## Non-Goals

- 今次唔改 pytest wrapper
- 今次唔自動探測 server version
- 今次唔改 restore script

## Testing

- 測試 subprocess command 內容是否改為 `docker run --rm ... postgres:17 pg_dump ...`
- 測試 Docker 缺失時會回傳可理解錯誤
- 測試 Docker 返回非零 exit code 時會回傳可理解錯誤
