# Database Index Documentation

This document provides comprehensive documentation for all database indices in the Agent Server schema.

## Table of Contents

1. [Index Overview](#index-overview)
2. [Index Strategy](#index-strategy)
3. [Index Categories](#index-categories)
4. [Table-by-Table Index Reference](#table-by-table-index-reference)
5. [Partial Index Details](#partial-index-details)
6. [Performance Considerations](#performance-considerations)

---

## Index Overview

The Agent Server database uses **59 indices** across 20 tables to optimize query performance:

| Index Type | Count | Purpose |
|------------|-------|---------|
| Primary Key | 20 | Unique row identification |
| Unique Constraint | 14 | Data integrity enforcement |
| Regular B-Tree | 25 | General query optimization |
| Partial Index | 10 | Filtered query optimization |
| **Total** | **69** | |

---

## Index Strategy

### Primary Keys
All tables use UUID primary keys with auto-generation via `gen_random_uuid()`.

### Foreign Keys
Foreign key columns are indexed to optimize JOIN operations and cascade deletes.

### Unique Constraints
Unique constraints are implemented as unique indices to enforce data integrity.

### Partial Indices
Partial indices are used extensively to optimize common query patterns:
- Queue polling for pending tasks
- Active schedule lookups
- Unresolved dead letter queue monitoring
- Default version enforcement

### Composite Indices
Composite indices optimize multi-column query patterns:
- User + timestamp combinations for activity queries
- Status + timestamp for status-based filtering
- Collaboration + timestamp for message ordering

---

## Index Categories

### 1. Lookup Indices
Optimize primary key and foreign key lookups.

### 2. Search Indices
Optimize text-based searches (usernames, emails, names).

### 3. Filtering Indices
Optimize status and boolean column filtering.

### 4. Ordering Indices
Optimize timestamp-based ordering (created_at, updated_at).

### 5. Partial Indices
Optimize filtered queries with WHERE clauses.

---

## Table-by-Table Index Reference

### User Management

#### `users`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `users_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `uq_users_username` | UNIQUE | `username` | Username uniqueness |
| `uq_users_email` | UNIQUE | `email` | Email uniqueness |
| `ix_users_username` | INDEX | `username` | Username search |
| `ix_users_email` | INDEX | `email` | Email search |

**Query Patterns Optimized:**
- User lookup by ID
- Login by username/email
- Duplicate checking on registration

---

#### `api_keys`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `api_keys_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `ix_api_keys_user_id` | INDEX | `user_id` | FK join optimization |

**Query Patterns Optimized:**
- API key lookup by ID
- Fetch all keys for a user

---

### Agent System

#### `agent_types`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `agent_types_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `uq_agent_types_name` | UNIQUE | `name` | Name uniqueness |
| `ix_agent_types_name` | INDEX | `name` | Name search |
| `idx_agent_types_is_active` | INDEX | `is_active` | Active type filtering |

**Query Patterns Optimized:**
- Agent type lookup by ID
- Find by name
- List active agent types

---

#### `agent_instances`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `agent_instances_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `ix_agent_instances_agent_type_id` | INDEX | `agent_type_id` | FK join optimization |
| `idx_agent_instances_status` | INDEX | `status` | Status filtering |
| `idx_agent_instances_user` | INDEX | `user_id` | FK join optimization |

**Query Patterns Optimized:**
- Agent instance lookup by ID
- Find all instances of a type
- Find agents by status (idle, busy, error, offline)
- Find all agents for a user

---

#### `agent_capabilities`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `agent_capabilities_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `idx_capabilities_type` | INDEX | `agent_type_id` | FK join optimization |
| `idx_capabilities_name` | INDEX | `capability_name` | Capability name search |

**Query Patterns Optimized:**
- Capability lookup by ID
- Find all capabilities for an agent type
- Search by capability name

---

### LLM Configuration

#### `llm_endpoint_groups`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `llm_endpoint_groups_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `uq_llm_endpoint_groups_name_per_user` | UNIQUE | `name, user_id` | Name uniqueness per user |
| `idx_llm_endpoint_groups_user` | INDEX | `user_id` | FK join optimization |
| `idx_llm_endpoint_groups_default` | PARTIAL UNIQUE | `user_id` | One default per user |

**Partial Index Condition:**
```sql
WHERE is_default = true
```

**Query Patterns Optimized:**
- Group lookup by ID
- Find all groups for a user
- Find user's default group (partial index)

---

#### `llm_endpoints`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `llm_endpoints_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `idx_endpoints_user` | INDEX | `user_id` | FK join optimization |

**Query Patterns Optimized:**
- Endpoint lookup by ID
- Find all endpoints for a user

---

#### `llm_level_endpoints`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `llm_level_endpoints_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `uq_llm_level_endpoints_endpoint_id` | UNIQUE | `endpoint_id` | One assignment per endpoint |
| `uq_llm_level_endpoints_group_level_secrets_endpoint` | UNIQUE | `group_id, difficulty_level, involves_secrets, endpoint_id` | Assignment uniqueness |
| `idx_level_endpoints_group` | INDEX | `group_id` | FK join optimization |

**Query Patterns Optimized:**
- Level endpoint lookup by ID
- Find all assignments for a group
- Check endpoint assignment uniqueness

---

### Collaboration

#### `collaboration_sessions`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `collaboration_sessions_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `uq_collaboration_sessions_session_id` | UNIQUE | `session_id` | Session ID uniqueness |
| `idx_collab_user` | INDEX | `user_id` | FK join optimization |
| `idx_collab_status` | INDEX | `status` | Status filtering |
| `ix_collaboration_sessions_main_agent_id` | INDEX | `main_agent_id` | FK join optimization |

**Query Patterns Optimized:**
- Session lookup by ID or session_id
- Find all sessions for a user
- Find sessions by status (active, completed, failed)
- Find sessions coordinated by an agent

---

#### `agent_messages`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `agent_messages_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `idx_messages_collab` | INDEX | `collaboration_id, created_at` | Message ordering |
| `idx_messages_step` | INDEX | `step_id` | Step-based grouping |
| `ix_agent_messages_collaboration_id` | INDEX | `collaboration_id` | FK join optimization |
| `ix_agent_messages_sender_agent_id` | INDEX | `sender_agent_id` | FK join optimization |
| `ix_agent_messages_receiver_agent_id` | INDEX | `receiver_agent_id` | FK join optimization |

**Query Patterns Optimized:**
- Message lookup by ID
- Fetch messages for a session (ordered by time)
- Find messages by step_id
- Find messages sent/received by an agent

---

### Task Management

#### `tasks`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `tasks_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `idx_tasks_status` | INDEX | `status, created_at` | Status filtering with ordering |
| `idx_tasks_user` | INDEX | `user_id, created_at` | User tasks with ordering |
| `idx_tasks_agent` | INDEX | `agent_id, created_at` | Agent tasks with ordering |
| `idx_tasks_scheduled` | INDEX | `scheduled_at` | Scheduled task lookup |
| `ix_tasks_parent_task_id` | INDEX | `parent_task_id` | Self-reference optimization |
| `idx_tasks_scheduled_pending` | PARTIAL | `scheduled_at` | Pending scheduled tasks |

**Partial Index Condition:**
```sql
WHERE status = 'pending'
```

**Query Patterns Optimized:**
- Task lookup by ID
- Find tasks by status (with ordering)
- Find all tasks for a user/agent
- Find scheduled tasks ready to execute (partial index)
- Find subtasks of a parent task

---

#### `task_dependencies`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `task_dependencies_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `uq_task_dependencies_parent_child` | UNIQUE | `parent_task_id, child_task_id` | Dependency uniqueness |
| `idx_deps_parent` | INDEX | `parent_task_id` | Parent lookup |
| `idx_deps_child` | INDEX | `child_task_id` | Child lookup |

**Query Patterns Optimized:**
- Dependency lookup by ID
- Find all dependencies for a task (as parent or child)
- Check for duplicate dependencies

---

#### `task_schedules`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `task_schedules_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `uq_task_schedules_template` | UNIQUE | `task_template_id` | One schedule per task |
| `ix_task_schedules_task_template_id` | INDEX | `task_template_id` | FK join optimization |
| `idx_schedules_next_run` | PARTIAL | `next_run_at` | Ready schedules |

**Partial Index Condition:**
```sql
WHERE is_active = true AND next_run_at IS NOT NULL
```

**Query Patterns Optimized:**
- Schedule lookup by ID
- Find schedule for a task
- Find schedules ready to execute (partial index - most critical for scheduler)

---

#### `task_queue`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `task_queue_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `ix_task_queue_task_id` | INDEX | `task_id` | FK join optimization |
| `ix_task_queue_claimed_by` | INDEX | `claimed_by` | FK join optimization |
| `idx_queue_poll` | PARTIAL | `priority DESC, scheduled_at ASC` | Queue polling |
| `idx_queue_claimed` | PARTIAL | `claimed_by` | Active task tracking |
| `idx_queue_retry` | PARTIAL | `retry_count` | Retry monitoring |

**Partial Index Conditions:**

| Index | Condition | Purpose |
|-------|-----------|---------|
| `idx_queue_poll` | `WHERE status = 'pending'` | Efficient queue polling - highest priority, earliest scheduled first |
| `idx_queue_claimed` | `WHERE status = 'running'` | Active task tracking by agent |
| `idx_queue_retry` | `WHERE status = 'pending'` | Retry monitoring for pending tasks |

**Query Patterns Optimized:**
- Queue entry lookup by ID
- Find queue entry for a task
- Poll for next task to process (partial index - critical)
- Find active tasks for an agent (partial index)
- Monitor retry counts (partial index)

---

#### `dead_letter_queue`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `dead_letter_queue_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `ix_dead_letter_queue_original_task_id` | INDEX | `original_task_id` | Task reference |
| `ix_dead_letter_queue_original_queue_entry_id` | INDEX | `original_queue_entry_id` | Queue entry reference |
| `ix_dead_letter_queue_resolved_by` | INDEX | `resolved_by` | FK join optimization |
| `idx_dlq_unresolved` | PARTIAL | `created_at DESC` | Unresolved items |
| `idx_dlq_resolved` | PARTIAL | `resolved_at DESC` | Resolved items |

**Partial Index Conditions:**

| Index | Condition | Purpose |
|-------|-----------|---------|
| `idx_dlq_unresolved` | `WHERE is_active = true` | Monitoring active DLQ items |
| `idx_dlq_resolved` | `WHERE resolved_at IS NOT NULL` | Historical review and auditing |

**Query Patterns Optimized:**
- DLQ entry lookup by ID
- Find DLQ entry for original task/queue entry
- Monitor unresolved failures (partial index - operational dashboard)
- Review resolved items (partial index - auditing)

---

### Tool System

#### `tools`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `tools_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `uq_tools_name` | UNIQUE | `name` | Name uniqueness |
| `ix_tools_name` | INDEX | `name` | Name search |
| `idx_tools_is_active` | INDEX | `is_active` | Active tool filtering |

**Query Patterns Optimized:**
- Tool lookup by ID
- Find tool by name
- List active tools

---

#### `tool_versions`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `tool_versions_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `ix_tool_versions_tool_id` | INDEX | `tool_id` | FK join optimization |
| `idx_tool_versions_version` | INDEX | `version` | Version search |
| `idx_tool_versions_default` | PARTIAL UNIQUE | `tool_id` | One default per tool |

**Partial Index Condition:**
```sql
WHERE is_default = true
```

**Query Patterns Optimized:**
- Version lookup by ID
- Find all versions for a tool
- Find default version for a tool (partial index)
- Search by version string

---

#### `tool_calls`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `tool_calls_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `idx_tool_calls_task` | INDEX | `task_id` | FK join optimization |
| `idx_tool_calls_tool` | INDEX | `tool_id` | FK join optimization |
| `ix_tool_calls_tool_version_id` | INDEX | `tool_version_id` | FK join optimization |

**Query Patterns Optimized:**
- Tool call lookup by ID
- Find all tool calls for a task
- Find all invocations of a tool
- Find calls using a specific version

---

### Observability

#### `token_usage`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `token_usage_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `idx_token_usage_user_created` | INDEX | `user_id, created_at` | User usage with ordering |
| `idx_token_usage_session` | INDEX | `session_id` | Session-based aggregation |

**Query Patterns Optimized:**
- Usage record lookup by ID
- Fetch usage history for a user (ordered by time)
- Aggregate usage by session

---

#### `audit.audit_log`

| Index Name | Type | Columns | Purpose |
|------------|------|---------|---------|
| `audit_log_pkey` | PRIMARY KEY | `id` | Primary key lookup |
| `idx_audit_user_time` | INDEX | `user_id, created_at DESC` | User activity queries |
| `idx_audit_resource` | INDEX | `resource_type, resource_id` | Resource history queries |

**Query Patterns Optimized:**
- Audit log lookup by ID
- Fetch user activity log (ordered by time)
- Find all audit entries for a resource

---

## Partial Index Details

### Summary of Partial Indices

| Table | Index Name | Condition | Purpose |
|-------|------------|-----------|---------|
| `llm_endpoint_groups` | `idx_llm_endpoint_groups_default` | `is_default = true` | Ensure one default per user |
| `tasks` | `idx_tasks_scheduled_pending` | `status = 'pending'` | Find scheduled tasks ready to run |
| `task_schedules` | `idx_schedules_next_run` | `is_active = true AND next_run_at IS NOT NULL` | Scheduler polling optimization |
| `task_queue` | `idx_queue_poll` | `status = 'pending'` | Queue polling - priority ordering |
| `task_queue` | `idx_queue_claimed` | `status = 'running'` | Active task tracking |
| `task_queue` | `idx_queue_retry` | `status = 'pending'` | Retry monitoring |
| `dead_letter_queue` | `idx_dlq_unresolved` | `is_active = true` | Unresolved failure monitoring |
| `dead_letter_queue` | `idx_dlq_resolved` | `resolved_at IS NOT NULL` | Resolved item auditing |
| `tool_versions` | `idx_tool_versions_default` | `is_default = true` | Ensure one default version per tool |

### Performance Impact

Partial indices provide significant performance benefits:

1. **Smaller Index Size**: Only relevant rows are indexed
2. **Faster Scans**: Fewer entries to traverse
3. **Reduced Maintenance**: Less overhead for INSERT/UPDATE/DELETE
4. **Targeted Optimization**: Indices are optimized for specific query patterns

---

## Performance Considerations

### Index Selection Guidelines

When adding new indices, consider:

1. **Query Patterns**: Index columns used in WHERE, JOIN, ORDER BY, GROUP BY
2. **Cardinality**: High-cardinality columns benefit more from indexing
3. **Selectivity**: Partial indices for highly selective conditions
4. **Write Load**: Balance read performance vs. write overhead

### Common Anti-Patterns to Avoid

1. **Over-Indexing**: Too many indices slow down writes
2. **Unused Indices**: Regularly audit and remove unused indices
3. **Duplicate Indices**: Avoid redundant index definitions
4. **Wide Indices**: Keep index column count reasonable

### Monitoring Queries

```sql
-- Find unused indices
SELECT schemaname, tablename, indexname
FROM pg_stat_user_indexes
WHERE idx_scan = 0;

-- Find index sizes
SELECT schemaname, tablename, indexname, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_stat_user_indexes
ORDER BY pg_relation_size(indexrelid) DESC;

-- Find index bloat
SELECT schemaname, tablename, indexname, pg_size_pretty(pg_relation_size(indexrelid)) as index_size
FROM pg_stat_user_indexes
WHERE pg_relation_size(indexrelid) > 10 * 1024 * 1024  -- > 10MB
ORDER BY pg_relation_size(indexrelid) DESC;
```

### Index Maintenance

```sql
-- Rebuild index
REINDEX INDEX CONCURRENTLY index_name;

-- Analyze table statistics
ANALYZE table_name;
```

---

## Appendix: Complete Index Listing

| Schema | Table | Index Name | Type | Columns |
|--------|-------|------------|------|---------|
| public | users | users_pkey | PRIMARY KEY | id |
| public | users | uq_users_username | UNIQUE | username |
| public | users | uq_users_email | UNIQUE | email |
| public | users | ix_users_username | INDEX | username |
| public | users | ix_users_email | INDEX | email |
| public | api_keys | api_keys_pkey | PRIMARY KEY | id |
| public | api_keys | ix_api_keys_user_id | INDEX | user_id |
| public | agent_types | agent_types_pkey | PRIMARY KEY | id |
| public | agent_types | uq_agent_types_name | UNIQUE | name |
| public | agent_types | ix_agent_types_name | INDEX | name |
| public | agent_types | idx_agent_types_is_active | INDEX | is_active |
| public | agent_instances | agent_instances_pkey | PRIMARY KEY | id |
| public | agent_instances | ix_agent_instances_agent_type_id | INDEX | agent_type_id |
| public | agent_instances | idx_agent_instances_status | INDEX | status |
| public | agent_instances | idx_agent_instances_user | INDEX | user_id |
| public | agent_capabilities | agent_capabilities_pkey | PRIMARY KEY | id |
| public | agent_capabilities | idx_capabilities_type | INDEX | agent_type_id |
| public | agent_capabilities | idx_capabilities_name | INDEX | capability_name |
| public | llm_endpoint_groups | llm_endpoint_groups_pkey | PRIMARY KEY | id |
| public | llm_endpoint_groups | uq_llm_endpoint_groups_name_per_user | UNIQUE | name, user_id |
| public | llm_endpoint_groups | idx_llm_endpoint_groups_user | INDEX | user_id |
| public | llm_endpoint_groups | idx_llm_endpoint_groups_default | PARTIAL UNIQUE | user_id |
| public | llm_endpoints | llm_endpoints_pkey | PRIMARY KEY | id |
| public | llm_endpoints | idx_endpoints_user | INDEX | user_id |
| public | llm_level_endpoints | llm_level_endpoints_pkey | PRIMARY KEY | id |
| public | llm_level_endpoints | uq_llm_level_endpoints_endpoint_id | UNIQUE | endpoint_id |
| public | llm_level_endpoints | uq_llm_level_endpoints_group_level_secrets_endpoint | UNIQUE | group_id, difficulty_level, involves_secrets, endpoint_id |
| public | llm_level_endpoints | idx_level_endpoints_group | INDEX | group_id |
| public | collaboration_sessions | collaboration_sessions_pkey | PRIMARY KEY | id |
| public | collaboration_sessions | uq_collaboration_sessions_session_id | UNIQUE | session_id |
| public | collaboration_sessions | idx_collab_user | INDEX | user_id |
| public | collaboration_sessions | idx_collab_status | INDEX | status |
| public | collaboration_sessions | ix_collaboration_sessions_main_agent_id | INDEX | main_agent_id |
| public | agent_messages | agent_messages_pkey | PRIMARY KEY | id |
| public | agent_messages | idx_messages_collab | INDEX | collaboration_id, created_at |
| public | agent_messages | idx_messages_step | INDEX | step_id |
| public | agent_messages | ix_agent_messages_collaboration_id | INDEX | collaboration_id |
| public | agent_messages | ix_agent_messages_sender_agent_id | INDEX | sender_agent_id |
| public | agent_messages | ix_agent_messages_receiver_agent_id | INDEX | receiver_agent_id |
| public | tasks | tasks_pkey | PRIMARY KEY | id |
| public | tasks | idx_tasks_status | INDEX | status, created_at |
| public | tasks | idx_tasks_user | INDEX | user_id, created_at |
| public | tasks | idx_tasks_agent | INDEX | agent_id, created_at |
| public | tasks | idx_tasks_scheduled | INDEX | scheduled_at |
| public | tasks | ix_tasks_parent_task_id | INDEX | parent_task_id |
| public | tasks | idx_tasks_scheduled_pending | PARTIAL | scheduled_at |
| public | task_dependencies | task_dependencies_pkey | PRIMARY KEY | id |
| public | task_dependencies | uq_task_dependencies_parent_child | UNIQUE | parent_task_id, child_task_id |
| public | task_dependencies | idx_deps_parent | INDEX | parent_task_id |
| public | task_dependencies | idx_deps_child | INDEX | child_task_id |
| public | task_schedules | task_schedules_pkey | PRIMARY KEY | id |
| public | task_schedules | uq_task_schedules_template | UNIQUE | task_template_id |
| public | task_schedules | ix_task_schedules_task_template_id | INDEX | task_template_id |
| public | task_schedules | idx_schedules_next_run | PARTIAL | next_run_at |
| public | task_queue | task_queue_pkey | PRIMARY KEY | id |
| public | task_queue | ix_task_queue_task_id | INDEX | task_id |
| public | task_queue | ix_task_queue_claimed_by | INDEX | claimed_by |
| public | task_queue | idx_queue_poll | PARTIAL | priority DESC, scheduled_at ASC |
| public | task_queue | idx_queue_claimed | PARTIAL | claimed_by |
| public | task_queue | idx_queue_retry | PARTIAL | retry_count |
| public | dead_letter_queue | dead_letter_queue_pkey | PRIMARY KEY | id |
| public | dead_letter_queue | ix_dead_letter_queue_original_task_id | INDEX | original_task_id |
| public | dead_letter_queue | ix_dead_letter_queue_original_queue_entry_id | INDEX | original_queue_entry_id |
| public | dead_letter_queue | ix_dead_letter_queue_resolved_by | INDEX | resolved_by |
| public | dead_letter_queue | idx_dlq_unresolved | PARTIAL | created_at DESC |
| public | dead_letter_queue | idx_dlq_resolved | PARTIAL | resolved_at DESC |
| public | tools | tools_pkey | PRIMARY KEY | id |
| public | tools | uq_tools_name | UNIQUE | name |
| public | tools | ix_tools_name | INDEX | name |
| public | tools | idx_tools_is_active | INDEX | is_active |
| public | tool_versions | tool_versions_pkey | PRIMARY KEY | id |
| public | tool_versions | ix_tool_versions_tool_id | INDEX | tool_id |
| public | tool_versions | idx_tool_versions_version | INDEX | version |
| public | tool_versions | idx_tool_versions_default | PARTIAL UNIQUE | tool_id |
| public | tool_calls | tool_calls_pkey | PRIMARY KEY | id |
| public | tool_calls | idx_tool_calls_task | INDEX | task_id |
| public | tool_calls | idx_tool_calls_tool | INDEX | tool_id |
| public | tool_calls | ix_tool_calls_tool_version_id | INDEX | tool_version_id |
| public | token_usage | token_usage_pkey | PRIMARY KEY | id |
| public | token_usage | idx_token_usage_user_created | INDEX | user_id, created_at |
| public | token_usage | idx_token_usage_session | INDEX | session_id |
| audit | audit_log | audit_log_pkey | PRIMARY KEY | id |
| audit | audit_log | idx_audit_user_time | INDEX | user_id, created_at DESC |
| audit | audit_log | idx_audit_resource | INDEX | resource_type, resource_id |