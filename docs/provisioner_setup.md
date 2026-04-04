# Provisioner Setup

## Required Environment

- `SANDBOX_BACKEND=remote_provisioner`
- `SANDBOX_PROVISIONER_URL=http://<provisioner-host>:8090`

## API Contract

Provisioner 目前支援：

1. `POST /api/sandboxes`
2. `GET /api/sandboxes/{sandbox_id}`
3. `DELETE /api/sandboxes/{sandbox_id}`
4. `GET /health`

## Next Step

要上 Kubernetes 時，建議將 `sandbox_provisioner.app` 內 in-memory registry 抽成 storage/orchestrator layer，再對接：

- Pod
- Service
- PVC
- readiness/liveness probe
- security context
