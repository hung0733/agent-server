# Docker Sandbox Architecture

## Overview

系統而家分成三層：

1. `SandboxProvider`
2. `SandboxBackend`
3. `Sandbox Agent API`

Provider 管 lifecycle、reuse、idle state；backend 決定本機 Docker 定 remote provisioner；真正 `exec/process` 透過 sandbox 內 agent API 執行。

## Virtual Paths

- `/mnt/data/workspace`
- `/mnt/data/uploads`
- `/mnt/data/outputs`
- `/mnt/skills`

Local backend 會將以上路徑映射到 `AGENT_HOME_DIR/{user_id}` 下面的 persistent host path；remote backend 可改用 PVC 或其他 volume provider。

## Execution Boundary

- `read/write/edit/grep/find/ls` 仍然沿用 host sandbox path policy
- `exec/process` 已改為走 sandbox provider
- host shell 不再係 sandbox mode 主路徑

## Backends

### Local Docker

- deterministic `sandbox_id`
- deterministic container name
- bind mount workspace
- HTTP sandbox agent endpoint

### Remote Provisioner

- idempotent create/get/delete API
- provider 只視其為 remote endpoint discovery service
- 後續可在 provisioner 實作 Pod/Service/PVC lifecycle
