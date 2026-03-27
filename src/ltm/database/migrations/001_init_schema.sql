-- SimpleMem Multi-Agent Database Schema
-- PostgreSQL 16+

-- ============================================================================
-- Create dedicated schema for LTM (Long-Term Memory)
-- Schema name from env: SIMPLEMEM_SCHEMA (default: simpleme)
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS simpleme;

-- ============================================================================
-- Dialogues Table
-- Stores all raw dialogue entries across agents and sessions
-- ============================================================================

CREATE TABLE IF NOT EXISTS simpleme.dialogues (
    dialogue_id BIGSERIAL PRIMARY KEY,
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    speaker TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_dialogues_agent_id ON simpleme.dialogues(agent_id);
CREATE INDEX IF NOT EXISTS idx_dialogues_session_id ON simpleme.dialogues(session_id);
CREATE INDEX IF NOT EXISTS idx_dialogues_agent_session ON simpleme.dialogues(agent_id, session_id);
CREATE INDEX IF NOT EXISTS idx_dialogues_created_at ON simpleme.dialogues(created_at DESC);

-- Comments
COMMENT ON TABLE simpleme.dialogues IS 'Stores raw dialogue entries for all agents and sessions';
COMMENT ON COLUMN simpleme.dialogues.agent_id IS 'String identifier for the agent (e.g., agent-{uuid}, butler-001)';
COMMENT ON COLUMN simpleme.dialogues.session_id IS 'String identifier for the session (e.g., default-{uuid}, session-{uuid})';
COMMENT ON COLUMN simpleme.dialogues.speaker IS 'Name of the dialogue speaker';
COMMENT ON COLUMN simpleme.dialogues.content IS 'Dialogue content';
COMMENT ON COLUMN simpleme.dialogues.timestamp IS 'Optional ISO 8601 timestamp from dialogue metadata';
COMMENT ON COLUMN simpleme.dialogues.created_at IS 'Record creation timestamp';
