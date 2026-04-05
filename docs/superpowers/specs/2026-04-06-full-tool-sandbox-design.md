# Full Tool Sandbox Design

## Goal

將所有 system tools 的實際執行入口統一收口到 `SandboxProvider`，令主 app 不再直接對 user workspace 做任何檔案或命令操作。

## Current State

- `exec/process` 已經會在有 `user_id` 時經 `SandboxProvider`
- `read/write/edit/apply_patch/grep/find/ls` 仍然直接在 host filesystem 操作，只靠 path security 限制
- `LocalDockerBackend` 已有真 Docker lifecycle；`RemoteProvisionerBackend` 已有 provisioner contract

## Chosen Approach

採用 provider 抽象統一、local backend 保留 volume fast path。

- tool layer 一律只 call `SandboxProvider`
- `LocalDockerBackend` 透過 host-mounted workspace 執行 file ops，但不再由 tool layer 直接操作
- `RemoteProvisionerBackend` file ops 經 sandbox agent API
- sandbox agent API 新增 file endpoints，作為 remote 與未來收緊 local path 的共同 contract

## Provider Contract

新增 provider/backend methods:

- `read_file`
- `write_file`
- `edit_file`
- `apply_patch`
- `grep_files`
- `find_files`
- `list_dir`

`system_tools.py` 對 user-scoped invocation 只負責：

1. 建 `SandboxRequest`
2. call `SandboxProvider`
3. format user-visible response

## Backend Contract

### Local Docker Backend

- 透過 `SandboxPathMapper` / backend-controlled host path helpers 做 file ops
- 仍然維持 `/mnt/...` virtual path display
- 不允許 tool layer 直接 `Path.read_text()/write_text()/glob()`

### Remote Provisioner Backend

- `read/write/edit/apply_patch/grep/find/ls` 走 sandbox agent HTTP API
- 不允許 fallback 到 host

## Sandbox Agent API

新增 endpoints:

- `POST /v1/files/read`
- `POST /v1/files/write`
- `POST /v1/files/edit`
- `POST /v1/files/apply-patch`
- `POST /v1/files/grep`
- `POST /v1/files/find`
- `POST /v1/files/list`

全部 endpoint 共用同一 token auth，同樣只接受 sandbox virtual path 或 sandbox-root-relative path。

## Migration Strategy

1. 先在 provider/backend 新增 file-op contract
2. 先將 `read/write/edit/ls` 切過 provider
3. 再切 `grep/find/apply_patch`
4. 補 remote backend file API client
5. 最後將 `tools.path_security` 降級為 path policy helper，而不是最終執行層

## Testing

- unit tests: system tools must delegate to provider for all file ops when `user_id` exists
- unit tests: local backend file ops preserve sandbox boundary and display paths
- integration tests: sandbox agent file API works with auth and workspace constraints
- integration tests: remote backend can use file endpoints through test client

## Scope Boundaries

- 今次不做新的 non-system tool sandboxing
- 今次不做 Kubernetes orchestration expansion
- 今次不把 local backend file ops 立即改成全 HTTP；只統一 tool abstraction
