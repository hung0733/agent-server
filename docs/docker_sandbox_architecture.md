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

- 所有 system tools 都先經 `SandboxProvider`
- `LocalDockerBackend` 對 file ops 仍可用 host-mounted volume fast path，但 tool layer 不再直接碰 host filesystem
- `RemoteProvisionerBackend` 的 file ops 與 `exec/process` 一樣走 sandbox agent HTTP API
- host shell / host file ops 都唔再係 sandbox mode 的 tool-layer 主路徑

## Backends

### Local Docker

- deterministic `sandbox_id`
- deterministic container name
- bind mount workspace
- HTTP sandbox agent endpoint
- backend now performs `docker inspect`, `docker run`, health polling, and `docker rm -f`

### Remote Provisioner

- idempotent create/get/delete API
- provider 只視其為 remote endpoint discovery service
- 後續可在 provisioner 實作 Pod/Service/PVC lifecycle
