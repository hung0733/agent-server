# Database Migration History

This document provides a comprehensive history of all database migrations in the Agent Server project.

## Table of Contents

1. [Migration Overview](#migration-overview)
2. [Migration Chain](#migration-chain)
3. [Migration Details](#migration-details)
4. [Rollback Procedures](#rollback-procedures)
5. [Migration Best Practices](#migration-best-practices)

---

## Migration Overview

The Agent Server database schema is managed using **Alembic** migrations. The migration history consists of **16 migrations** that build the complete database schema.

### Migration Statistics

| Metric | Value |
|--------|-------|
| Total Migrations | 16 |
| Tables Created | 20 |
| Tables in Public Schema | 19 |
| Tables in Audit Schema | 1 |
| Migration Date Range | 2026-03-22 |

### Migration Naming Convention

Migrations use a standardized naming pattern:
- Auto-generated: `{revision_id}_{description}.py`
- Revision IDs: 12-character hexadecimal strings
- Descriptions: Snake_case table or feature descriptions

---

## Migration Chain

```
7f86bcdf9b7c (baseline) ─┬─> a1b2c3d4e5f6 ──> b2c3d4e5f6g7 ──> c3d4e5f6g7h8 ──> d4e5f6g7h8i9 ──> d8022d08a7f4 ─┐
                         │                                                                                │
                         │                           c4d5e6f7g8h9 ──> e5f6g7h8i9j0 ──> f6g7h8i9j0k1 ──>        │
                         │                           ▲                                                │
                         └───────────────────────────┘                                                │
                                                                                                      │
                         ──> g7h8i9j0k1l2 ──> h8i9j0k1l2m3 ──> i9j0k1l2m3n4 ──> j0k1l2m3n4o5 ──>       │
                                                                                                      │
                                                                                                      ▼
                         k1l2m3n4o5p6 ──> l2m3n4o5p6q7 ────────────────────────────────────────> 6e2241c2c7f2 (merge)
```

### Linear Migration Order

| Order | Revision | Description |
|-------|----------|-------------|
| 1 | `7f86bcdf9b7c` | Create users and api_keys tables (baseline) |
| 2 | `a1b2c3d4e5f6` | Create audit schema and audit_log table |
| 3 | `b2c3d4e5f6g7` | Create agent_types and agent_instances tables |
| 4 | `c3d4e5f6g7h8` | Create llm_endpoint_groups table |
| 5 | `d4e5f6g7h8i9` | Create llm_endpoints and llm_level_endpoints tables |
| 6 | `d8022d08a7f4` | Create agent_capabilities table |
| 7 | `c4d5e6f7g8h9` | Create collaboration_sessions and agent_messages tables |
| 8 | `e5f6g7h8i9j0` | Create tasks table |
| 9 | `f6g7h8i9j0k1` | Create task_dependencies table |
| 10 | `g7h8i9j0k1l2` | Create task_schedules table |
| 11 | `h8i9j0k1l2m3` | Create task_queue table |
| 12 | `i9j0k1l2m3n4` | Create dead_letter_queue table |
| 13 | `j0k1l2m3n4o5` | Create tools and tool_versions tables |
| 14 | `k1l2m3n4o5p6` | Add tool_calls table |
| 15 | `l2m3n4o5p6q7` | Add token_usage table |
| 16 | `6e2241c2c7f2` | Merge heads |

---

## Migration Details

### 1. `7f86bcdf9b7c` - Create users and api_keys tables (Baseline)

**Date:** 2026-03-22 13:13:27  
**Revises:** None (baseline)

**Purpose:**
Creates the foundational user management tables for authentication and authorization.

**Tables Created:**
- `users` - User account storage
- `api_keys` - API key authentication

**Schema Changes:**
```sql
-- users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT NOT NULL,
    email TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Unique constraints
ALTER TABLE users ADD CONSTRAINT uq_users_username UNIQUE (username);
ALTER TABLE users ADD CONSTRAINT uq_users_email UNIQUE (email);

-- Indexes
CREATE INDEX ix_users_username ON users(username);
CREATE INDEX ix_users_email ON users(email);

-- api_keys table
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL,
    name TEXT,
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Index
CREATE INDEX ix_api_keys_user_id ON api_keys(user_id);
```

---

### 2. `a1b2c3d4e5f6` - Create audit schema and audit_log table

**Date:** 2026-03-22 14:00:00  
**Revises:** `7f86bcdf9b7c`

**Purpose:**
Creates a separate audit schema for immutable audit logging.

**Schema Changes:**
```sql
-- Create audit schema
CREATE SCHEMA IF NOT EXISTS audit;

-- Create enum type
CREATE TYPE actor_type_enum AS ENUM ('user', 'agent', 'system');

-- Create audit_log table
CREATE TABLE audit.audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    actor_type actor_type_enum NOT NULL,
    actor_id UUID NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID NOT NULL,
    old_values JSONB,
    new_values JSONB,
    ip_address INET,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX idx_audit_user_time ON audit.audit_log(user_id, created_at DESC);
CREATE INDEX idx_audit_resource ON audit.audit_log(resource_type, resource_id);
```

---

### 3. `b2c3d4e5f6g7` - Create agent_types and agent_instances tables

**Date:** 2026-03-22 15:00:00  
**Revises:** `a1b2c3d4e5f6`

**Purpose:**
Creates the agent system core tables for defining and running agents.

**Tables Created:**
- `agent_types` - Agent type definitions
- `agent_instances` - Runtime agent instances

**Schema Changes:**
```sql
-- agent_types table
CREATE TABLE agent_types (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    capabilities JSONB,
    default_config JSONB,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_agent_types_name UNIQUE (name)
);

-- Indexes
CREATE INDEX ix_agent_types_name ON agent_types(name);
CREATE INDEX idx_agent_types_is_active ON agent_types(is_active);

-- agent_instances table
CREATE TABLE agent_instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_type_id UUID NOT NULL REFERENCES agent_types(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'idle',
    config JSONB,
    last_heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_agent_instances_status 
        CHECK (status IN ('idle', 'busy', 'error', 'offline'))
);

-- Indexes
CREATE INDEX ix_agent_instances_agent_type_id ON agent_instances(agent_type_id);
CREATE INDEX idx_agent_instances_status ON agent_instances(status);
CREATE INDEX idx_agent_instances_user ON agent_instances(user_id);
```

---

### 4. `c3d4e5f6g7h8` - Create llm_endpoint_groups table

**Date:** 2026-03-22 16:00:00  
**Revises:** `b2c3d4e5f6g7`

**Purpose:**
Creates LLM endpoint groups for user-level endpoint organization.

**Schema Changes:**
```sql
CREATE TABLE llm_endpoint_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_llm_endpoint_groups_name_per_user UNIQUE (name, user_id)
);

-- Indexes
CREATE INDEX idx_llm_endpoint_groups_user ON llm_endpoint_groups(user_id);

-- Partial unique index for default group
CREATE UNIQUE INDEX CONCURRENTLY idx_llm_endpoint_groups_default
    ON llm_endpoint_groups(user_id)
    WHERE is_default = true;
```

---

### 5. `d4e5f6g7h8i9` - Create llm_endpoints and llm_level_endpoints tables

**Date:** 2026-03-22 17:00:00  
**Revises:** `c3d4e5f6g7h8`

**Purpose:**
Creates LLM endpoint configurations and difficulty-level assignments.

**Tables Created:**
- `llm_endpoints` - LLM API endpoint configurations
- `llm_level_endpoints` - Endpoint to difficulty level mappings

**Schema Changes:**
```sql
-- llm_endpoints table
CREATE TABLE llm_endpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    base_url TEXT NOT NULL,
    api_key_encrypted TEXT NOT NULL,
    model_name TEXT NOT NULL,
    config_json JSONB,
    is_active BOOLEAN NOT NULL DEFAULT true,
    last_success_at TIMESTAMPTZ,
    last_failure_at TIMESTAMPTZ,
    failure_count INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_endpoints_user ON llm_endpoints(user_id);

-- llm_level_endpoints table
CREATE TABLE llm_level_endpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id UUID NOT NULL REFERENCES llm_endpoint_groups(id) ON DELETE CASCADE,
    difficulty_level SMALLINT NOT NULL,
    involves_secrets BOOLEAN NOT NULL DEFAULT false,
    endpoint_id UUID NOT NULL REFERENCES llm_endpoints(id) ON DELETE CASCADE,
    priority INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_llm_level_endpoints_endpoint_id UNIQUE (endpoint_id),
    CONSTRAINT uq_llm_level_endpoints_group_level_secrets_endpoint 
        UNIQUE (group_id, difficulty_level, involves_secrets, endpoint_id),
    CONSTRAINT ck_llm_level_endpoints_difficulty_level 
        CHECK (difficulty_level BETWEEN 1 AND 3)
);

CREATE INDEX idx_level_endpoints_group ON llm_level_endpoints(group_id);
```

---

### 6. `d8022d08a7f4` - Create agent_capabilities table

**Date:** 2026-03-22 14:26:55  
**Revises:** `d4e5f6g7h8i9`

**Purpose:**
Creates agent capabilities for defining what agent types can do.

**Schema Changes:**
```sql
CREATE TABLE agent_capabilities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_type_id UUID NOT NULL REFERENCES agent_types(id) ON DELETE CASCADE,
    capability_name TEXT NOT NULL,
    description TEXT,
    input_schema JSONB,
    output_schema JSONB,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX idx_capabilities_type ON agent_capabilities(agent_type_id);
CREATE INDEX idx_capabilities_name ON agent_capabilities(capability_name);
```

---

### 7. `c4d5e6f7g8h9` - Create collaboration_sessions and agent_messages tables

**Date:** 2026-03-22 16:00:00  
**Revises:** `b2c3d4e5f6g7` (branch from earlier migration)

**Purpose:**
Creates multi-agent collaboration support.

**Tables Created:**
- `collaboration_sessions` - Collaboration session management
- `agent_messages` - Inter-agent message tracking

**Schema Changes:**
```sql
-- collaboration_sessions table
CREATE TABLE collaboration_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    main_agent_id UUID NOT NULL REFERENCES agent_instances(id) ON DELETE CASCADE,
    name TEXT,
    session_id TEXT NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    involves_secrets BOOLEAN NOT NULL DEFAULT false,
    context_json JSONB,
    ended_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_collaboration_sessions_session_id UNIQUE (session_id),
    CONSTRAINT ck_collaboration_sessions_status 
        CHECK (status IN ('active', 'completed', 'failed', 'cancelled'))
);

-- Indexes
CREATE INDEX idx_collab_user ON collaboration_sessions(user_id);
CREATE INDEX idx_collab_status ON collaboration_sessions(status);
CREATE INDEX ix_collaboration_sessions_main_agent_id ON collaboration_sessions(main_agent_id);

-- agent_messages table
CREATE TABLE agent_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    collaboration_id UUID NOT NULL REFERENCES collaboration_sessions(id) ON DELETE CASCADE,
    step_id TEXT,
    sender_agent_id UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
    receiver_agent_id UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
    message_type VARCHAR(50) NOT NULL DEFAULT 'request',
    content_json JSONB NOT NULL,
    redaction_level VARCHAR(50) NOT NULL DEFAULT 'none',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_agent_messages_message_type 
        CHECK (message_type IN ('request', 'response', 'notification', 'ack', 'tool_call', 'tool_result')),
    CONSTRAINT ck_agent_messages_redaction_level 
        CHECK (redaction_level IN ('none', 'partial', 'full'))
);

-- Indexes
CREATE INDEX idx_messages_collab ON agent_messages(collaboration_id, created_at);
CREATE INDEX idx_messages_step ON agent_messages(step_id);
CREATE INDEX ix_agent_messages_collaboration_id ON agent_messages(collaboration_id);
CREATE INDEX ix_agent_messages_sender_agent_id ON agent_messages(sender_agent_id);
CREATE INDEX ix_agent_messages_receiver_agent_id ON agent_messages(receiver_agent_id);
```

---

### 8. `e5f6g7h8i9j0` - Create tasks table

**Date:** 2026-03-22 16:00:00  
**Revises:** `c4d5e6f7g8h9`

**Purpose:**
Creates the core task management table.

**Schema Changes:**
```sql
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
    parent_task_id UUID REFERENCES tasks(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL,
    session_id TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    priority VARCHAR(50) NOT NULL DEFAULT 'normal',
    payload JSONB,
    result JSONB,
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    scheduled_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_tasks_status CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    CONSTRAINT ck_tasks_priority CHECK (priority IN ('low', 'normal', 'high', 'critical')),
    CONSTRAINT ck_tasks_retry_count CHECK (retry_count >= 0),
    CONSTRAINT ck_tasks_max_retries CHECK (max_retries >= 0)
);

-- Indexes
CREATE INDEX idx_tasks_status ON tasks(status, created_at);
CREATE INDEX idx_tasks_user ON tasks(user_id, created_at);
CREATE INDEX idx_tasks_agent ON tasks(agent_id, created_at);
CREATE INDEX idx_tasks_scheduled ON tasks(scheduled_at);
CREATE INDEX ix_tasks_parent_task_id ON tasks(parent_task_id);

-- Partial index for scheduled tasks
CREATE INDEX CONCURRENTLY idx_tasks_scheduled_pending
    ON tasks(scheduled_at)
    WHERE status = 'pending';
```

---

### 9. `f6g7h8i9j0k1` - Create task_dependencies table

**Date:** 2026-03-22 18:00:00  
**Revises:** `e5f6g7h8i9j0`

**Purpose:**
Creates task dependency tracking for workflow orchestration.

**Schema Changes:**
```sql
CREATE TABLE task_dependencies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    child_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    dependency_type VARCHAR(50) NOT NULL DEFAULT 'sequential',
    condition_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_task_dependencies_no_self_reference 
        CHECK (parent_task_id != child_task_id)
);

-- Unique constraint
ALTER TABLE task_dependencies 
    ADD CONSTRAINT uq_task_dependencies_parent_child 
    UNIQUE (parent_task_id, child_task_id);

-- Indexes
CREATE INDEX idx_deps_parent ON task_dependencies(parent_task_id);
CREATE INDEX idx_deps_child ON task_dependencies(child_task_id);
```

---

### 10. `g7h8i9j0k1l2` - Create task_schedules table

**Date:** 2026-03-22 19:00:00  
**Revises:** `f6g7h8i9j0k1`

**Purpose:**
Creates scheduled task templates for recurring execution.

**Schema Changes:**
```sql
CREATE TABLE task_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_template_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    schedule_type VARCHAR(50) NOT NULL DEFAULT 'cron',
    schedule_expression TEXT NOT NULL,
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_task_schedules_template UNIQUE (task_template_id),
    CONSTRAINT ck_task_schedules_schedule_type 
        CHECK (schedule_type IN ('once', 'interval', 'cron'))
);

-- Indexes
CREATE INDEX ix_task_schedules_task_template_id ON task_schedules(task_template_id);

-- Partial index for active schedules
CREATE INDEX CONCURRENTLY idx_schedules_next_run
    ON task_schedules(next_run_at ASC)
    WHERE is_active = true AND next_run_at IS NOT NULL;
```

---

### 11. `h8i9j0k1l2m3` - Create task_queue table

**Date:** 2026-03-22 20:00:00  
**Revises:** `g7h8i9j0k1l2`

**Purpose:**
Creates the task execution queue with claiming support.

**Schema Changes:**
```sql
CREATE TABLE task_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 0,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    scheduled_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    claimed_by UUID REFERENCES agent_instances(id) ON DELETE SET NULL,
    claimed_at TIMESTAMPTZ,
    retry_count INTEGER NOT NULL DEFAULT 0,
    max_retries INTEGER NOT NULL DEFAULT 3,
    error_message TEXT,
    result_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_task_queue_status 
        CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    CONSTRAINT ck_task_queue_retry_count CHECK (retry_count >= 0),
    CONSTRAINT ck_task_queue_max_retries CHECK (max_retries >= 0),
    CONSTRAINT ck_task_queue_priority CHECK (priority >= 0)
);

-- Regular indexes
CREATE INDEX ix_task_queue_task_id ON task_queue(task_id);
CREATE INDEX ix_task_queue_claimed_by ON task_queue(claimed_by);

-- Partial indexes for queue operations
CREATE INDEX CONCURRENTLY idx_queue_poll
    ON task_queue(priority DESC, scheduled_at ASC)
    WHERE status = 'pending';

CREATE INDEX CONCURRENTLY idx_queue_claimed
    ON task_queue(claimed_by)
    WHERE status = 'running';

CREATE INDEX CONCURRENTLY idx_queue_retry
    ON task_queue(retry_count)
    WHERE status = 'pending';
```

---

### 12. `i9j0k1l2m3n4` - Create dead_letter_queue table

**Date:** 2026-03-22 21:00:00  
**Revises:** `h8i9j0k1l2m3`

**Purpose:**
Creates dead letter queue for failed task tracking.

**Schema Changes:**
```sql
CREATE TABLE dead_letter_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_task_id UUID REFERENCES tasks(id) ON DELETE SET NULL,
    original_queue_entry_id UUID REFERENCES task_queue(id) ON DELETE CASCADE,
    original_payload_json JSONB NOT NULL,
    failure_reason TEXT NOT NULL,
    failure_details_json JSONB NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    dead_lettered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_dead_letter_queue_retry_count CHECK (retry_count >= 0)
);

-- Regular indexes
CREATE INDEX ix_dead_letter_queue_original_task_id ON dead_letter_queue(original_task_id);
CREATE INDEX ix_dead_letter_queue_original_queue_entry_id ON dead_letter_queue(original_queue_entry_id);
CREATE INDEX ix_dead_letter_queue_resolved_by ON dead_letter_queue(resolved_by);

-- Partial indexes
CREATE INDEX CONCURRENTLY idx_dlq_unresolved
    ON dead_letter_queue(created_at DESC)
    WHERE is_active = true;

CREATE INDEX CONCURRENTLY idx_dlq_resolved
    ON dead_letter_queue(resolved_at DESC)
    WHERE resolved_at IS NOT NULL;
```

---

### 13. `j0k1l2m3n4o5` - Create tools and tool_versions tables

**Date:** 2026-03-22 16:20:00  
**Revises:** `i9j0k1l2m3n4`

**Purpose:**
Creates tool registry with versioning support.

**Tables Created:**
- `tools` - Tool definitions
- `tool_versions` - Versioned tool configurations

**Schema Changes:**
```sql
-- tools table
CREATE TABLE tools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_tools_name UNIQUE (name)
);

-- Indexes
CREATE INDEX ix_tools_name ON tools(name);
CREATE INDEX idx_tools_is_active ON tools(is_active);

-- tool_versions table
CREATE TABLE tool_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_id UUID NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    version VARCHAR(50) NOT NULL,
    input_schema JSONB,
    output_schema JSONB,
    implementation_ref TEXT,
    config_json JSONB,
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX ix_tool_versions_tool_id ON tool_versions(tool_id);
CREATE INDEX idx_tool_versions_version ON tool_versions(version);

-- Partial unique index for default version
CREATE UNIQUE INDEX CONCURRENTLY idx_tool_versions_default
    ON tool_versions(tool_id)
    WHERE is_default = true;
```

---

### 14. `k1l2m3n4o5p6` - Add tool_calls table

**Date:** 2026-03-22 16:30:00  
**Revises:** `j0k1l2m3n4o5`

**Purpose:**
Creates tool call tracking.

**Schema Changes:**
```sql
CREATE TABLE tool_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    tool_id UUID NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    tool_version_id UUID REFERENCES tool_versions(id) ON DELETE SET NULL,
    input JSONB,
    output JSONB,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_tool_calls_status 
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    CONSTRAINT ck_tool_calls_duration_ms CHECK (duration_ms >= 0)
);

-- Indexes
CREATE INDEX idx_tool_calls_task ON tool_calls(task_id);
CREATE INDEX idx_tool_calls_tool ON tool_calls(tool_id);
CREATE INDEX ix_tool_calls_tool_version_id ON tool_calls(tool_version_id);
```

---

### 15. `l2m3n4o5p6q7` - Add token_usage table

**Date:** 2026-03-22 16:30:00  
**Revises:** `k1l2m3n4o5p6`

**Purpose:**
Creates token usage tracking for LLM cost monitoring.

**Schema Changes:**
```sql
CREATE TABLE token_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES agent_instances(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    estimated_cost_usd NUMERIC(10, 6) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX idx_token_usage_user_created ON token_usage(user_id, created_at);
CREATE INDEX idx_token_usage_session ON token_usage(session_id);
```

---

### 16. `6e2241c2c7f2` - Merge heads

**Date:** 2026-03-22 18:32:54  
**Revises:** `d8022d08a7f4`, `l2m3n4o5p6q7`

**Purpose:**
Merges parallel migration branches into a single head.

**Schema Changes:**
None (migration only resolves branch divergence).

---

## Rollback Procedures

### Full Rollback

To rollback all migrations to a clean database:

```bash
# Drop all tables and schemas
alembic downgrade base
```

### Partial Rollback

To rollback to a specific migration:

```bash
# Rollback to a specific revision
alembic downgrade <revision_id>

# Example: Rollback to before tool system
alembic downgrade j0k1l2m3n4o5
```

### Single Migration Rollback

To rollback one migration:

```bash
alembic downgrade -1
```

---

## Migration Best Practices

### Creating New Migrations

```bash
# Auto-generate migration from model changes
alembic revision --autogenerate -m "description of changes"

# Create empty migration for custom SQL
alembic revision -m "description of changes"
```

### Running Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Apply up to a specific revision
alembic upgrade <revision_id>

# Apply one migration
alembic upgrade +1
```

### Migration Guidelines

1. **Always review auto-generated migrations** before applying
2. **Test migrations on a development database** first
3. **Backup production data** before applying migrations
4. **Use `CONCURRENTLY` for index creation** in production
5. **Avoid long-running transactions** in migrations
6. **Include both upgrade and downgrade** methods
7. **Add meaningful docstrings** to migration files

### Data Migration Considerations

For migrations that include data transformations:

1. Create a new migration for schema changes
2. Create a separate script for data migration
3. Run data migration in batches for large tables
4. Consider using background jobs for large data migrations

---

## Appendix: Quick Reference

### Current Head

```
6e2241c2c7f2 (merge_heads)
```

### Migration Files Location

```
alembic/versions/
```

### Check Current Revision

```bash
alembic current
```

### View Migration History

```bash
alembic history
```

### Generate Migration SQL (without applying)

```bash
alembic upgrade head --sql
```