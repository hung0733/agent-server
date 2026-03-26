-- SimpleMem Multi-Agent Database Schema
-- PostgreSQL 16+

-- ============================================================================
-- Dialogues Table
-- Stores all raw dialogue entries across agents and sessions
-- ============================================================================

CREATE TABLE IF NOT EXISTS dialogues (
    dialogue_id BIGSERIAL PRIMARY KEY,
    agent_id UUID NOT NULL,
    session_id UUID NOT NULL,
    speaker TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_dialogues_agent_id ON dialogues(agent_id);
CREATE INDEX IF NOT EXISTS idx_dialogues_session_id ON dialogues(session_id);
CREATE INDEX IF NOT EXISTS idx_dialogues_agent_session ON dialogues(agent_id, session_id);
CREATE INDEX IF NOT EXISTS idx_dialogues_created_at ON dialogues(created_at DESC);

-- Comments
COMMENT ON TABLE dialogues IS 'Stores raw dialogue entries for all agents and sessions';
COMMENT ON COLUMN dialogues.agent_id IS 'UUID identifying the agent (tenant isolation)';
COMMENT ON COLUMN dialogues.session_id IS 'UUID identifying the conversation session';
COMMENT ON COLUMN dialogues.speaker IS 'Name of the dialogue speaker';
COMMENT ON COLUMN dialogues.content IS 'Dialogue content';
COMMENT ON COLUMN dialogues.timestamp IS 'Optional ISO 8601 timestamp from dialogue metadata';
COMMENT ON COLUMN dialogues.created_at IS 'Record creation timestamp';
