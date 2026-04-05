# Full Tool Sandbox Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Route all system tools through `SandboxProvider` so the main app no longer directly executes user-scoped file operations on the host.

**Architecture:** Extend the sandbox provider/backend contract with file operations, teach `system_tools.py` to delegate all user-scoped file tools through the provider, implement local backend fast-path file operations, and add sandbox agent file endpoints for remote backends. The tool layer becomes provider-only while local/remote behavior diverges only inside backends.

**Tech Stack:** Python 3.12, FastAPI, Docker, pytest

---

### Task 1: Add failing delegation tests

**Files:**
- Modify: `tests/unit/test_system_tools_security.py`
- Test: `tests/unit/test_system_tools_security.py`

- [ ] Add tests proving `read/write/edit/apply_patch/grep/find/ls` call `SandboxProvider` when `user_id` exists.
- [ ] Run: `python3 -m pytest tests/unit/test_system_tools_security.py -v`
- [ ] Confirm failures point to missing provider file-op support.

### Task 2: Extend provider/backend contract

**Files:**
- Modify: `src/sandbox/backends/base.py`
- Modify: `src/sandbox/provider.py`
- Modify: `tests/unit/test_sandbox_provider.py`

- [ ] Add file-op methods to backend and provider.
- [ ] Add tests proving provider routes and releases handles for file ops.
- [ ] Run targeted tests until green.

### Task 3: Implement local backend file fast path

**Files:**
- Modify: `src/sandbox/backends/local_docker.py`
- Modify: `tests/unit/test_local_docker_backend.py`

- [ ] Add local backend file implementations using backend-controlled host paths.
- [ ] Keep sandbox boundary and display-path semantics.
- [ ] Run targeted tests until green.

### Task 4: Add sandbox agent file API and remote backend client

**Files:**
- Modify: `src/sandbox_agent/app.py`
- Create or Modify: `src/sandbox_agent/file_ops.py`
- Modify: `src/sandbox/backends/remote_provisioner.py`
- Modify: `tests/integration/test_sandbox_agent_api.py`
- Modify: `tests/unit/test_remote_provisioner_backend.py`

- [ ] Add file endpoints to sandbox agent.
- [ ] Add remote backend HTTP client methods for file ops.
- [ ] Run targeted tests until green.

### Task 5: Switch system tools to provider-only user path

**Files:**
- Modify: `src/tools/system_tools.py`
- Modify: `tests/unit/test_system_tools_security.py`

- [ ] Replace direct host file ops in user-scoped tool flow with provider calls.
- [ ] Keep legacy non-user flow unchanged.
- [ ] Run targeted tests until green.

### Task 6: Verify and document

**Files:**
- Modify: `docs/docker_sandbox_architecture.md`
- Modify: `docs/sandbox_deployment_checklist.md`

- [ ] Update docs to note that all system tools route through provider.
- [ ] Run focused unit + integration suite.
- [ ] Commit changes.
