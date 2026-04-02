-- DROP ALL TABLES IN public SCHEMA
-- WARNING: This will permanently delete all tables and data!
-- Use with EXTREME caution!

-- Usage:
--   psql -h 192.168.1.252 -U agentserver -d agentserver -f scripts/drop_all_tables.sql

BEGIN;

-- Disable foreign key constraints to avoid dependency issues
SET session_replication_role = 'replica';

-- Drop all tables in public schema
DROP TABLE IF EXISTS public."agent_capabilities" CASCADE;
DROP TABLE IF EXISTS public."agent_instance_tools" CASCADE;
DROP TABLE IF EXISTS public."agent_instances" CASCADE;
DROP TABLE IF EXISTS public."agent_messages" CASCADE;
DROP TABLE IF EXISTS public."agent_type_tools" CASCADE;
DROP TABLE IF EXISTS public."agent_types" CASCADE;
DROP TABLE IF EXISTS public."alembic_version" CASCADE;
DROP TABLE IF EXISTS public."api_keys" CASCADE;
DROP TABLE IF EXISTS public."collaboration_sessions" CASCADE;
DROP TABLE IF EXISTS public."dead_letter_queue" CASCADE;
DROP TABLE IF EXISTS public."llm_endpoint_groups" CASCADE;
DROP TABLE IF EXISTS public."llm_endpoints" CASCADE;
DROP TABLE IF EXISTS public."llm_level_endpoints" CASCADE;
DROP TABLE IF EXISTS public."mcp_clients" CASCADE;
DROP TABLE IF EXISTS public."mcp_tools" CASCADE;
DROP TABLE IF EXISTS public."memory_blocks" CASCADE;
DROP TABLE IF EXISTS public."task_dependencies" CASCADE;
DROP TABLE IF EXISTS public."task_queue" CASCADE;
DROP TABLE IF EXISTS public."task_schedules" CASCADE;
DROP TABLE IF EXISTS public."tasks" CASCADE;
DROP TABLE IF EXISTS public."token_usage" CASCADE;
DROP TABLE IF EXISTS public."tool_calls" CASCADE;
DROP TABLE IF EXISTS public."tool_versions" CASCADE;
DROP TABLE IF EXISTS public."tools" CASCADE;
DROP TABLE IF EXISTS public."users" CASCADE;

-- Re-enable foreign key constraints
SET session_replication_role = 'origin';

COMMIT;

-- After running this script, you need to recreate the schema:
--   alembic upgrade head
