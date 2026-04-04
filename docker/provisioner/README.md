# Sandbox Provisioner

Provisioner 係 remote sandbox backend 的 HTTP facade。

目前提供：

- `POST /api/sandboxes`
- `GET /api/sandboxes/{sandbox_id}`
- `DELETE /api/sandboxes/{sandbox_id}`
- `GET /health`

第一版先交付 idempotent API contract，同本機測試用 in-memory registry。之後可將 `build_provisioner_app()` 的 storage layer 換成 Kubernetes Pod/Service/PVC orchestration。
