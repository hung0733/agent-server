# Sandbox Deployment Checklist

## Local Docker Sandbox

Required environment variables:

- `AGENT_HOME_DIR`
- `SANDBOX_BACKEND=local_docker`
- `SANDBOX_AGENT_BASE_URL`
- `SANDBOX_API_TOKEN`
- `SANDBOX_PROVIDER=aio`
- `SANDBOX_DEFAULT_PROFILE=default`
- `SANDBOX_IDLE_TIMEOUT_SECONDS=1800`

Quick start:

1. Copy `/.env.example` to a real env file for your environment
2. Replace all token placeholders with unique secrets
3. Point `AGENT_HOME_DIR` to a persistent writable host directory

Recommended runtime checks:

1. Confirm Docker daemon is reachable: `docker ps`
2. Confirm sandbox image exists or can be built: `docker build -f docker/sandbox/Dockerfile .`
3. Confirm writable workspace root exists under `AGENT_HOME_DIR`
4. Confirm `SANDBOX_API_TOKEN` is set explicitly and not reused from examples
5. Confirm app can reach sandbox agent health endpoint after container start

## Remote Provisioner Sandbox

Required environment variables:

- `SANDBOX_BACKEND=remote_provisioner`
- `SANDBOX_PROVISIONER_URL`
- `SANDBOX_PROVISIONER_TOKEN`
- `SANDBOX_PROVIDER=aio`
- `SANDBOX_DEFAULT_PROFILE=default`
- `SANDBOX_IDLE_TIMEOUT_SECONDS=1800`

Quick start:

1. Start from `/.env.example`
2. Uncomment the remote provisioner block and set real endpoint/token values
3. Keep local and remote tokens separate

Recommended runtime checks:

1. Confirm provisioner health: `curl -H "X-Provisioner-Token: $SANDBOX_PROVISIONER_TOKEN" "$SANDBOX_PROVISIONER_URL/health"`
2. Confirm provisioner can create, fetch, and delete sandbox records
3. Confirm returned sandbox endpoint exposes `/health`
4. Confirm remote storage mapping for workspace, uploads, outputs, and skills

## Security Checklist

1. Use unique secrets for `SANDBOX_API_TOKEN` and `SANDBOX_PROVISIONER_TOKEN`
2. Do not expose sandbox agent or provisioner without auth headers
3. Run sandbox containers as non-root
4. Restrict writable mounts to `/workspace` and explicit temp paths only
5. Review Docker socket / orchestration permissions before production rollout
