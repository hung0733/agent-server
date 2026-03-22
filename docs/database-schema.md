# Database Schema Documentation

This document provides comprehensive documentation for the Agent Server database schema.

## Table of Contents

1. [Overview](#overview)
2. [Schema Organization](#schema-organization)
3. [Common Patterns](#common-patterns)
4. [Table Definitions](#table-definitions)
   - [User Management](#user-management)
   - [Agent System](#agent-system)
   - [LLM Configuration](#llm-configuration)
   - [Collaboration](#collaboration)
   - [Task Management](#task-management)
   - [Tool System](#tool-system)
   - [Observability](#observability)
5. [Enum Types](#enum-types)
6. [Constraints Reference](#constraints-reference)

---

## Overview

The Agent Server database is designed to support a multi-tenant agent orchestration platform with the following key capabilities:

- **User Management**: Multi-user support with API key authentication
- **Agent System**: Configurable agent types with runtime instances
- **LLM Configuration**: Flexible LLM endpoint management with difficulty-based routing
- **Collaboration**: Multi-agent collaboration sessions with message tracking
- **Task Management**: Comprehensive task lifecycle with dependencies, scheduling, and queuing
- **Tool System**: Extensible tool registry with versioning
- **Observability**: Token usage tracking and audit logging

**Database Technology**: PostgreSQL 15+
**Primary Key Type**: UUID v4 (`gen_random_uuid()`)
**Timestamp Type**: `timestamptz` (UTC timezone-aware)

---

## Schema Organization

### Public Schema (Default)

All operational tables reside in the `public` schema:

| Domain | Tables |
|--------|--------|
| User Management | `users`, `api_keys` |
| Agent System | `agent_types`, `agent_instances`, `agent_capabilities` |
| LLM Configuration | `llm_endpoint_groups`, `llm_endpoints`, `llm_level_endpoints` |
| Collaboration | `collaboration_sessions`, `agent_messages` |
| Task Management | `tasks`, `task_dependencies`, `task_schedules`, `task_queue`, `dead_letter_queue` |
| Tool System | `tools`, `tool_versions`, `tool_calls` |
| Observability | `token_usage` |

### Audit Schema

The `audit` schema contains audit logging tables:

| Table | Purpose |
|-------|---------|
| `audit_log` | Immutable audit trail for all system actions |

---

## Common Patterns

### Primary Keys

All tables use UUID v4 primary keys:

```sql
id UUID PRIMARY KEY DEFAULT gen_random_uuid()
```

### Timestamps

All tables include creation and update timestamps:

```sql
created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
```

### Soft Delete Pattern

Tables that support soft deletion use an `is_active` boolean column:

```sql
is_active BOOLEAN NOT NULL DEFAULT true
```

### JSONB Storage

Flexible data is stored in JSONB columns:

```sql
payload JSONB,
config_json JSONB,
schema JSONB
```

---

## Table Definitions

### User Management

#### `users`

Stores user account information.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `username` | TEXT | NO | - | Unique username for login |
| `email` | TEXT | NO | - | Unique email address |
| `is_active` | BOOLEAN | NO | `true` | Account active status |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Constraints:**
- `uq_users_username`: Unique constraint on `username`
- `uq_users_email`: Unique constraint on `email`

**Indexes:**
- `ix_users_username`: Index on `username` (unique)
- `ix_users_email`: Index on `email` (unique)

---

#### `api_keys`

Stores API key hashes for user authentication.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `user_id` | UUID | NO | - | Foreign key to `users.id` |
| `key_hash` | TEXT | NO | - | Hashed API key (never plain text) |
| `name` | TEXT | YES | - | Human-readable key name |
| `last_used_at` | TIMESTAMPTZ | YES | - | Last usage timestamp |
| `expires_at` | TIMESTAMPTZ | YES | - | Optional expiration timestamp |
| `is_active` | BOOLEAN | NO | `true` | Key active status |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `user_id` → `users.id` (ON DELETE CASCADE)

**Indexes:**
- `ix_api_keys_user_id`: Index on `user_id`

---

### Agent System

#### `agent_types`

Defines agent type templates with capabilities and default configurations.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `name` | TEXT | NO | - | Unique agent type name |
| `description` | TEXT | YES | - | Human-readable description |
| `capabilities` | JSONB | YES | - | Capability key-value pairs |
| `default_config` | JSONB | YES | - | Default configuration |
| `is_active` | BOOLEAN | NO | `true` | Type active status |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Constraints:**
- `uq_agent_types_name`: Unique constraint on `name`

**Indexes:**
- `ix_agent_types_name`: Index on `name` (unique)
- `idx_agent_types_is_active`: Index on `is_active`

---

#### `agent_instances`

Runtime instances of agent types.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `agent_type_id` | UUID | NO | - | Foreign key to `agent_types.id` |
| `user_id` | UUID | NO | - | Foreign key to `users.id` |
| `name` | TEXT | YES | - | Optional instance name |
| `status` | VARCHAR(50) | NO | `'idle'` | Instance status |
| `config` | JSONB | YES | - | Instance-specific config |
| `last_heartbeat_at` | TIMESTAMPTZ | YES | - | Last heartbeat timestamp |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `agent_type_id` → `agent_types.id` (ON DELETE CASCADE)
- `user_id` → `users.id` (ON DELETE CASCADE)

**Check Constraints:**
- `ck_agent_instances_status`: `status IN ('idle', 'busy', 'error', 'offline')`

**Indexes:**
- `ix_agent_instances_agent_type_id`: Index on `agent_type_id`
- `idx_agent_instances_status`: Index on `status`
- `idx_agent_instances_user`: Index on `user_id`

---

#### `agent_capabilities`

Defines capabilities for agent types.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `agent_type_id` | UUID | NO | - | Foreign key to `agent_types.id` |
| `capability_name` | TEXT | NO | - | Name of the capability |
| `description` | TEXT | YES | - | Human-readable description |
| `input_schema` | JSONB | YES | - | JSON Schema for input validation |
| `output_schema` | JSONB | YES | - | JSON Schema for output validation |
| `is_active` | BOOLEAN | NO | `true` | Capability active status |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `agent_type_id` → `agent_types.id` (ON DELETE CASCADE)

**Indexes:**
- `idx_capabilities_type`: Index on `agent_type_id`
- `idx_capabilities_name`: Index on `capability_name`

---

### LLM Configuration

#### `llm_endpoint_groups`

Groups of LLM endpoints for user-level configuration.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `user_id` | UUID | NO | - | Foreign key to `users.id` |
| `name` | TEXT | NO | - | Group name |
| `description` | TEXT | YES | - | Group description |
| `is_default` | BOOLEAN | NO | `false` | User's default group |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `user_id` → `users.id` (ON DELETE CASCADE)

**Constraints:**
- `uq_llm_endpoint_groups_name_per_user`: Unique constraint on `(name, user_id)`

**Indexes:**
- `idx_llm_endpoint_groups_user`: Index on `user_id`
- `idx_llm_endpoint_groups_default`: Partial unique index on `user_id` WHERE `is_default = true`

---

#### `llm_endpoints`

Individual LLM API endpoint configurations.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `user_id` | UUID | NO | - | Foreign key to `users.id` |
| `name` | TEXT | NO | - | Human-readable endpoint name |
| `base_url` | TEXT | NO | - | Base URL for the LLM API |
| `api_key_encrypted` | TEXT | NO | - | Encrypted API key |
| `model_name` | TEXT | NO | - | Model name (e.g., 'gpt-4') |
| `config_json` | JSONB | YES | - | Advanced configuration |
| `is_active` | BOOLEAN | NO | `true` | Endpoint active status |
| `last_success_at` | TIMESTAMPTZ | YES | - | Last successful call timestamp |
| `last_failure_at` | TIMESTAMPTZ | YES | - | Last failed call timestamp |
| `failure_count` | INTEGER | NO | `0` | Consecutive failure count |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `user_id` → `users.id` (ON DELETE CASCADE)

**Indexes:**
- `idx_endpoints_user`: Index on `user_id`

---

#### `llm_level_endpoints`

Maps endpoints to difficulty levels within groups.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `group_id` | UUID | NO | - | Foreign key to `llm_endpoint_groups.id` |
| `endpoint_id` | UUID | NO | - | Foreign key to `llm_endpoints.id` |
| `difficulty_level` | SMALLINT | NO | - | Difficulty level (1-3) |
| `involves_secrets` | BOOLEAN | NO | `false` | Handles secrets/sensitive data |
| `priority` | INTEGER | NO | `0` | Selection priority (higher = preferred) |
| `is_active` | BOOLEAN | NO | `true` | Assignment active status |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |

**Foreign Keys:**
- `group_id` → `llm_endpoint_groups.id` (ON DELETE CASCADE)
- `endpoint_id` → `llm_endpoints.id` (ON DELETE CASCADE)

**Check Constraints:**
- `ck_llm_level_endpoints_difficulty_level`: `difficulty_level BETWEEN 1 AND 3`

**Constraints:**
- `uq_llm_level_endpoints_endpoint_id`: Unique constraint on `endpoint_id`
- `uq_llm_level_endpoints_group_level_secrets_endpoint`: Unique constraint on `(group_id, difficulty_level, involves_secrets, endpoint_id)`

**Indexes:**
- `idx_level_endpoints_group`: Index on `group_id`

---

### Collaboration

#### `collaboration_sessions`

Multi-agent collaboration sessions.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `user_id` | UUID | NO | - | Foreign key to `users.id` |
| `main_agent_id` | UUID | NO | - | Foreign key to `agent_instances.id` |
| `name` | TEXT | YES | - | Optional session name |
| `session_id` | TEXT | NO | - | Unique session identifier |
| `status` | VARCHAR(50) | NO | `'active'` | Session status |
| `involves_secrets` | BOOLEAN | NO | `false` | Involves sensitive data |
| `context_json` | JSONB | YES | - | Shared session context |
| `ended_at` | TIMESTAMPTZ | YES | - | Session end timestamp |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `user_id` → `users.id` (ON DELETE CASCADE)
- `main_agent_id` → `agent_instances.id` (ON DELETE CASCADE)

**Check Constraints:**
- `ck_collaboration_sessions_status`: `status IN ('active', 'completed', 'failed', 'cancelled')`

**Constraints:**
- `uq_collaboration_sessions_session_id`: Unique constraint on `session_id`

**Indexes:**
- `idx_collab_user`: Index on `user_id`
- `idx_collab_status`: Index on `status`
- `ix_collaboration_sessions_main_agent_id`: Index on `main_agent_id`

---

#### `agent_messages`

Messages exchanged between agents in collaborations.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `collaboration_id` | UUID | NO | - | Foreign key to `collaboration_sessions.id` |
| `step_id` | TEXT | YES | - | Step identifier for grouping |
| `sender_agent_id` | UUID | YES | - | Foreign key to sender `agent_instances.id` |
| `receiver_agent_id` | UUID | YES | - | Foreign key to receiver `agent_instances.id` |
| `message_type` | VARCHAR(50) | NO | `'request'` | Message type |
| `content_json` | JSONB | NO | - | Message content |
| `redaction_level` | VARCHAR(50) | NO | `'none'` | Content redaction level |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |

**Foreign Keys:**
- `collaboration_id` → `collaboration_sessions.id` (ON DELETE CASCADE)
- `sender_agent_id` → `agent_instances.id` (ON DELETE SET NULL)
- `receiver_agent_id` → `agent_instances.id` (ON DELETE SET NULL)

**Check Constraints:**
- `ck_agent_messages_message_type`: `message_type IN ('request', 'response', 'notification', 'ack', 'tool_call', 'tool_result')`
- `ck_agent_messages_redaction_level`: `redaction_level IN ('none', 'partial', 'full')`

**Indexes:**
- `idx_messages_collab`: Index on `(collaboration_id, created_at)`
- `idx_messages_step`: Index on `step_id`
- `ix_agent_messages_collaboration_id`: Index on `collaboration_id`
- `ix_agent_messages_sender_agent_id`: Index on `sender_agent_id`
- `ix_agent_messages_receiver_agent_id`: Index on `receiver_agent_id`

---

### Task Management

#### `tasks`

Core task definitions with lifecycle tracking.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `user_id` | UUID | NO | - | Foreign key to `users.id` |
| `agent_id` | UUID | YES | - | Foreign key to `agent_instances.id` |
| `parent_task_id` | UUID | YES | - | Self-reference for task hierarchies |
| `task_type` | TEXT | NO | - | Type of task |
| `session_id` | TEXT | YES | - | LangGraph thread ID |
| `status` | VARCHAR(50) | NO | `'pending'` | Execution status |
| `priority` | VARCHAR(50) | NO | `'normal'` | Task priority |
| `payload` | JSONB | YES | - | Task specifications |
| `result` | JSONB | YES | - | Execution results |
| `error_message` | TEXT | YES | - | Error message if failed |
| `retry_count` | INTEGER | NO | `0` | Number of retry attempts |
| `max_retries` | INTEGER | NO | `3` | Maximum retry attempts |
| `scheduled_at` | TIMESTAMPTZ | YES | - | Scheduled execution time |
| `started_at` | TIMESTAMPTZ | YES | - | Execution start time |
| `completed_at` | TIMESTAMPTZ | YES | - | Completion time |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `user_id` → `users.id` (ON DELETE CASCADE)
- `agent_id` → `agent_instances.id` (ON DELETE SET NULL)
- `parent_task_id` → `tasks.id` (ON DELETE CASCADE)

**Check Constraints:**
- `ck_tasks_status`: `status IN ('pending', 'running', 'completed', 'failed', 'cancelled')`
- `ck_tasks_priority`: `priority IN ('low', 'normal', 'high', 'critical')`
- `ck_tasks_retry_count`: `retry_count >= 0`
- `ck_tasks_max_retries`: `max_retries >= 0`

**Indexes:**
- `idx_tasks_status`: Index on `(status, created_at)`
- `idx_tasks_user`: Index on `(user_id, created_at)`
- `idx_tasks_agent`: Index on `(agent_id, created_at)`
- `idx_tasks_scheduled`: Index on `scheduled_at`
- `ix_tasks_parent_task_id`: Index on `parent_task_id`
- `idx_tasks_scheduled_pending`: Partial index on `scheduled_at` WHERE `status = 'pending'`

---

#### `task_dependencies`

Defines dependencies between tasks.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `parent_task_id` | UUID | NO | - | Parent task (must complete first) |
| `child_task_id` | UUID | NO | - | Child task (depends on parent) |
| `dependency_type` | VARCHAR(50) | NO | `'sequential'` | Type of dependency |
| `condition_json` | JSONB | YES | - | Conditional logic for conditional deps |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `parent_task_id` → `tasks.id` (ON DELETE CASCADE)
- `child_task_id` → `tasks.id` (ON DELETE CASCADE)

**Check Constraints:**
- `ck_task_dependencies_no_self_reference`: `parent_task_id != child_task_id`

**Constraints:**
- `uq_task_dependencies_parent_child`: Unique constraint on `(parent_task_id, child_task_id)`

**Indexes:**
- `idx_deps_parent`: Index on `parent_task_id`
- `idx_deps_child`: Index on `child_task_id`

---

#### `task_schedules`

Recurring and scheduled task templates.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `task_template_id` | UUID | NO | - | Foreign key to `tasks.id` |
| `schedule_type` | VARCHAR(50) | NO | `'cron'` | Type of schedule |
| `schedule_expression` | TEXT | NO | - | Schedule expression |
| `next_run_at` | TIMESTAMPTZ | YES | - | Next scheduled execution |
| `last_run_at` | TIMESTAMPTZ | YES | - | Last execution timestamp |
| `is_active` | BOOLEAN | NO | `true` | Schedule active status |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `task_template_id` → `tasks.id` (ON DELETE CASCADE)

**Check Constraints:**
- `ck_task_schedules_schedule_type`: `schedule_type IN ('once', 'interval', 'cron')`
- `ck_task_schedules_cron_format`: Validates cron expression format
- `ck_task_schedules_interval_format`: Validates ISO 8601 duration format
- `ck_task_schedules_once_format`: Validates ISO 8601 timestamp format

**Constraints:**
- `uq_task_schedules_template`: Unique constraint on `task_template_id`

**Indexes:**
- `ix_task_schedules_task_template_id`: Index on `task_template_id`
- `idx_schedules_next_run`: Partial index on `next_run_at` WHERE `is_active = true AND next_run_at IS NOT NULL`

---

#### `task_queue`

Execution queue for tasks with claiming support.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `task_id` | UUID | NO | - | Foreign key to `tasks.id` |
| `status` | VARCHAR(50) | NO | `'pending'` | Queue entry status |
| `priority` | INTEGER | NO | `0` | Execution priority (higher = first) |
| `queued_at` | TIMESTAMPTZ | NO | `now()` | Queue entry timestamp |
| `scheduled_at` | TIMESTAMPTZ | YES | - | Scheduled availability time |
| `started_at` | TIMESTAMPTZ | YES | - | Execution start time |
| `completed_at` | TIMESTAMPTZ | YES | - | Completion time |
| `claimed_by` | UUID | YES | - | Claiming agent instance ID |
| `claimed_at` | TIMESTAMPTZ | YES | - | Claim timestamp |
| `retry_count` | INTEGER | NO | `0` | Number of retry attempts |
| `max_retries` | INTEGER | NO | `3` | Maximum retry attempts |
| `error_message` | TEXT | YES | - | Error message if failed |
| `result_json` | JSONB | YES | - | Execution results |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `task_id` → `tasks.id` (ON DELETE CASCADE)
- `claimed_by` → `agent_instances.id` (ON DELETE SET NULL)

**Check Constraints:**
- `ck_task_queue_status`: `status IN ('pending', 'running', 'completed', 'failed', 'cancelled')`
- `ck_task_queue_retry_count`: `retry_count >= 0`
- `ck_task_queue_max_retries`: `max_retries >= 0`
- `ck_task_queue_priority`: `priority >= 0`

**Indexes:**
- `ix_task_queue_task_id`: Index on `task_id`
- `ix_task_queue_claimed_by`: Index on `claimed_by`
- `idx_queue_poll`: Partial index on `(priority DESC, scheduled_at ASC)` WHERE `status = 'pending'`
- `idx_queue_claimed`: Partial index on `claimed_by` WHERE `status = 'running'`
- `idx_queue_retry`: Partial index on `retry_count` WHERE `status = 'pending'`

---

#### `dead_letter_queue`

Failed tasks preserved for debugging and potential reprocessing.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `original_task_id` | UUID | YES | - | Original task ID (NULL if deleted) |
| `original_queue_entry_id` | UUID | YES | - | Original queue entry ID |
| `original_payload_json` | JSONB | NO | - | Complete original payload |
| `failure_reason` | TEXT | NO | - | Error classification |
| `failure_details_json` | JSONB | NO | - | Full error context |
| `retry_count` | INTEGER | NO | `0` | Number of times moved to DLQ |
| `last_attempt_at` | TIMESTAMPTZ | YES | - | Last failure timestamp |
| `dead_lettered_at` | TIMESTAMPTZ | NO | `now()` | DLQ entry timestamp |
| `resolved_at` | TIMESTAMPTZ | YES | - | Resolution timestamp |
| `resolved_by` | UUID | YES | - | User who resolved |
| `is_active` | BOOLEAN | NO | `true` | Unresolved status |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `original_task_id` → `tasks.id` (ON DELETE SET NULL)
- `original_queue_entry_id` → `task_queue.id` (ON DELETE CASCADE)
- `resolved_by` → `users.id` (ON DELETE SET NULL)

**Check Constraints:**
- `ck_dead_letter_queue_retry_count`: `retry_count >= 0`

**Indexes:**
- `ix_dead_letter_queue_original_task_id`: Index on `original_task_id`
- `ix_dead_letter_queue_original_queue_entry_id`: Index on `original_queue_entry_id`
- `ix_dead_letter_queue_resolved_by`: Index on `resolved_by`
- `idx_dlq_unresolved`: Partial index on `created_at DESC` WHERE `is_active = true`
- `idx_dlq_resolved`: Partial index on `resolved_at DESC` WHERE `resolved_at IS NOT NULL`

---

### Tool System

#### `tools`

Registry of available tools.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `name` | TEXT | NO | - | Unique tool name |
| `description` | TEXT | YES | - | Human-readable description |
| `is_active` | BOOLEAN | NO | `true` | Tool active status |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Constraints:**
- `uq_tools_name`: Unique constraint on `name`

**Indexes:**
- `ix_tools_name`: Index on `name`
- `idx_tools_is_active`: Index on `is_active`

---

#### `tool_versions`

Versioned tool definitions with schemas.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `tool_id` | UUID | NO | - | Foreign key to `tools.id` |
| `version` | VARCHAR(50) | NO | - | Version string (e.g., '1.0.0') |
| `input_schema` | JSONB | YES | - | JSON Schema for input validation |
| `output_schema` | JSONB | YES | - | JSON Schema for output validation |
| `implementation_ref` | TEXT | YES | - | Implementation reference |
| `config_json` | JSONB | YES | - | Tool-specific configuration |
| `is_default` | BOOLEAN | NO | `false` | Default version flag |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |

**Foreign Keys:**
- `tool_id` → `tools.id` (ON DELETE CASCADE)

**Indexes:**
- `ix_tool_versions_tool_id`: Index on `tool_id`
- `idx_tool_versions_version`: Index on `version`
- `idx_tool_versions_default`: Partial unique index on `tool_id` WHERE `is_default = true`

---

#### `tool_calls`

Records of tool invocations.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `task_id` | UUID | NO | - | Foreign key to `tasks.id` |
| `tool_id` | UUID | NO | - | Foreign key to `tools.id` |
| `tool_version_id` | UUID | YES | - | Foreign key to `tool_versions.id` |
| `input` | JSONB | YES | - | Input parameters |
| `output` | JSONB | YES | - | Output/results |
| `status` | VARCHAR(50) | NO | `'pending'` | Execution status |
| `error_message` | TEXT | YES | - | Error message if failed |
| `duration_ms` | INTEGER | YES | - | Execution duration in ms |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `task_id` → `tasks.id` (ON DELETE CASCADE)
- `tool_id` → `tools.id` (ON DELETE CASCADE)
- `tool_version_id` → `tool_versions.id` (ON DELETE SET NULL)

**Check Constraints:**
- `ck_tool_calls_status`: `status IN ('pending', 'running', 'completed', 'failed')`
- `ck_tool_calls_duration_ms`: `duration_ms >= 0`

**Indexes:**
- `idx_tool_calls_task`: Index on `task_id`
- `idx_tool_calls_tool`: Index on `tool_id`
- `ix_tool_calls_tool_version_id`: Index on `tool_version_id`

---

### Observability

#### `token_usage`

Token usage tracking for LLM API calls.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `user_id` | UUID | NO | - | Foreign key to `users.id` |
| `agent_id` | UUID | NO | - | Foreign key to `agent_instances.id` |
| `session_id` | TEXT | NO | - | Session identifier |
| `model_name` | TEXT | NO | - | LLM model name |
| `input_tokens` | INTEGER | NO | - | Input token count |
| `output_tokens` | INTEGER | NO | - | Output token count |
| `total_tokens` | INTEGER | NO | - | Total token count |
| `estimated_cost_usd` | NUMERIC(10,6) | NO | - | Estimated cost in USD |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |
| `updated_at` | TIMESTAMPTZ | NO | `now()` | Last update timestamp |

**Foreign Keys:**
- `user_id` → `users.id` (ON DELETE CASCADE)
- `agent_id` → `agent_instances.id` (ON DELETE CASCADE)

**Indexes:**
- `idx_token_usage_user_created`: Index on `(user_id, created_at)`
- `idx_token_usage_session`: Index on `session_id`

---

#### `audit.audit_log` (Audit Schema)

Immutable audit trail for all system actions.

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `id` | UUID | NO | `gen_random_uuid()` | Primary key |
| `user_id` | UUID | YES | - | User who performed action |
| `actor_type` | actor_type_enum | NO | - | Type of actor (user/agent/system) |
| `actor_id` | UUID | NO | - | Actor identifier |
| `action` | TEXT | NO | - | Action performed |
| `resource_type` | TEXT | NO | - | Type of resource affected |
| `resource_id` | UUID | NO | - | Resource identifier |
| `old_values` | JSONB | YES | - | Previous state |
| `new_values` | JSONB | YES | - | New state |
| `ip_address` | INET | YES | - | Origin IP address |
| `created_at` | TIMESTAMPTZ | NO | `now()` | Creation timestamp |

**Indexes:**
- `idx_audit_user_time`: Index on `(user_id, created_at DESC)`
- `idx_audit_resource`: Index on `(resource_type, resource_id)`

---

## Enum Types

### `actor_type_enum`

Defined in the `audit` schema:

| Value | Description |
|-------|-------------|
| `user` | Action performed by a human user |
| `agent` | Action performed by an automated agent |
| `system` | Action performed by the system itself |

### Application-Level Enums (VARCHAR with Check Constraints)

#### `AgentStatus`

Used in `agent_instances.status`:

| Value | Description |
|-------|-------------|
| `idle` | Agent is available and waiting for tasks |
| `busy` | Agent is currently executing a task |
| `error` | Agent encountered an error |
| `offline` | Agent is disconnected or unavailable |

#### `TaskStatus`

Used in `tasks.status` and `task_queue.status`:

| Value | Description |
|-------|-------------|
| `pending` | Task is queued and waiting |
| `running` | Task is currently executing |
| `completed` | Task finished successfully |
| `failed` | Task execution failed |
| `cancelled` | Task was cancelled |

#### `Priority`

Used in `tasks.priority`:

| Value | Description |
|-------|-------------|
| `low` | Low priority - execute when resources available |
| `normal` | Normal priority - standard scheduling |
| `high` | High priority - execute before normal tasks |
| `critical` | Critical priority - execute immediately |

#### `DependencyType`

Used in `task_dependencies.dependency_type`:

| Value | Description |
|-------|-------------|
| `sequential` | Tasks must execute one after another |
| `parallel` | Tasks can execute concurrently |
| `conditional` | Execution depends on another task's outcome |

#### `ScheduleType`

Used in `task_schedules.schedule_type`:

| Value | Description |
|-------|-------------|
| `once` | One-time schedule (ISO 8601 timestamp) |
| `interval` | Recurring interval (ISO 8601 duration) |
| `cron` | Cron expression (5-part unix format) |

#### `CollaborationStatus`

Used in `collaboration_sessions.status`:

| Value | Description |
|-------|-------------|
| `active` | Session is currently active |
| `completed` | Session completed successfully |
| `failed` | Session failed |
| `cancelled` | Session was cancelled |

#### `MessageType`

Used in `agent_messages.message_type`:

| Value | Description |
|-------|-------------|
| `request` | Request message |
| `response` | Response message |
| `notification` | Notification message |
| `ack` | Acknowledgment message |
| `tool_call` | Tool call message |
| `tool_result` | Tool result message |

#### `RedactionLevel`

Used in `agent_messages.redaction_level`:

| Value | Description |
|-------|-------------|
| `none` | No redaction |
| `partial` | Partial redaction |
| `full` | Full redaction |

#### `ToolCallStatus`

Used in `tool_calls.status`:

| Value | Description |
|-------|-------------|
| `pending` | Tool call is pending |
| `running` | Tool call is executing |
| `completed` | Tool call completed successfully |
| `failed` | Tool call failed |

---

## Constraints Reference

### Unique Constraints

| Table | Constraint Name | Columns |
|-------|-----------------|---------|
| users | uq_users_username | username |
| users | uq_users_email | email |
| agent_types | uq_agent_types_name | name |
| llm_endpoint_groups | uq_llm_endpoint_groups_name_per_user | name, user_id |
| llm_level_endpoints | uq_llm_level_endpoints_endpoint_id | endpoint_id |
| llm_level_endpoints | uq_llm_level_endpoints_group_level_secrets_endpoint | group_id, difficulty_level, involves_secrets, endpoint_id |
| collaboration_sessions | uq_collaboration_sessions_session_id | session_id |
| task_dependencies | uq_task_dependencies_parent_child | parent_task_id, child_task_id |
| task_schedules | uq_task_schedules_template | task_template_id |
| tools | uq_tools_name | name |

### Check Constraints

| Table | Constraint Name | Condition |
|-------|-----------------|-----------|
| agent_instances | ck_agent_instances_status | status IN ('idle', 'busy', 'error', 'offline') |
| llm_level_endpoints | ck_llm_level_endpoints_difficulty_level | difficulty_level BETWEEN 1 AND 3 |
| collaboration_sessions | ck_collaboration_sessions_status | status IN ('active', 'completed', 'failed', 'cancelled') |
| agent_messages | ck_agent_messages_message_type | message_type IN ('request', 'response', 'notification', 'ack', 'tool_call', 'tool_result') |
| agent_messages | ck_agent_messages_redaction_level | redaction_level IN ('none', 'partial', 'full') |
| tasks | ck_tasks_status | status IN ('pending', 'running', 'completed', 'failed', 'cancelled') |
| tasks | ck_tasks_priority | priority IN ('low', 'normal', 'high', 'critical') |
| tasks | ck_tasks_retry_count | retry_count >= 0 |
| tasks | ck_tasks_max_retries | max_retries >= 0 |
| task_dependencies | ck_task_dependencies_no_self_reference | parent_task_id != child_task_id |
| task_schedules | ck_task_schedules_schedule_type | schedule_type IN ('once', 'interval', 'cron') |
| task_queue | ck_task_queue_status | status IN ('pending', 'running', 'completed', 'failed', 'cancelled') |
| task_queue | ck_task_queue_retry_count | retry_count >= 0 |
| task_queue | ck_task_queue_max_retries | max_retries >= 0 |
| task_queue | ck_task_queue_priority | priority >= 0 |
| dead_letter_queue | ck_dead_letter_queue_retry_count | retry_count >= 0 |
| tool_calls | ck_tool_calls_status | status IN ('pending', 'running', 'completed', 'failed') |
| tool_calls | ck_tool_calls_duration_ms | duration_ms >= 0 |