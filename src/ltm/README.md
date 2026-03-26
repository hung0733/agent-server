# SimpleMem Multi-Agent LTM Module

This is a packaged version of SimpleMem multi-agent long-term memory system for use in the agent-server project.

## Overview

SimpleMem is a semantic lossless compression framework for efficient long-term memory in LLM agents with:
- **Complete agent isolation** via agent_id
- **Cross-session memory sharing** (same agent across sessions)
- **DB-based context retrieval** (PostgreSQL + Qdrant)
- **Async API** with parallel processing support

## Installation

### 1. Install Dependencies

```bash
pip install -r ltm/DEPENDENCIES.txt
```

### 2. Set Up Databases

Start Qdrant and PostgreSQL using Docker:

```bash
docker run -d -p 6333:6333 -p 6334:6334 \
    -v qdrant_data:/qdrant/storage \
    qdrant/qdrant:latest

docker run -d -p 5432:5432 \
    -e POSTGRES_USER=simplemem \
    -e POSTGRES_PASSWORD=simplemem \
    -e POSTGRES_DB=simplemem \
    -v postgres_data:/var/lib/postgresql/data \
    postgres:16-alpine
```

### 3. Initialize PostgreSQL Schema

```bash
psql -h localhost -U simplemem -d simplemem -f ltm/database/migrations/001_init_schema.sql
```

### 4. Configure Environment

Create a `.env` file or set environment variables:

```bash
# LLM Configuration
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gpt-4o-mini"
export OPENAI_BASE_URL="https://api.openai.com/v1"

# Qdrant Configuration
export QDRANT_URL="http://localhost:6333"
export QDRANT_COLLECTION_NAME="simplemem_memories"

# PostgreSQL Configuration
export POSTGRES_URL="postgresql://simplemem:simplemem@localhost:5432/simplemem"
```

## Usage

### Basic Example

```python
import asyncio
import uuid
from ltm.simplemem import create_system

async def main():
    # Create agent
    agent_id = str(uuid.uuid4())
    system = await create_system(agent_id=agent_id)

    # Create session
    session_id = str(uuid.uuid4())

    # Add dialogues
    await system.add_dialogue(
        session_id=session_id,
        speaker="User",
        content="Let's meet at Starbucks at 2pm tomorrow",
        timestamp="2025-11-15T14:00:00"
    )

    await system.add_dialogue(
        session_id=session_id,
        speaker="Assistant",
        content="Sure, I'll be there. What should I bring?",
        timestamp="2025-11-15T14:01:00"
    )

    # Finalize session (process dialogues and store to Qdrant)
    await system.finalize(session_id)

    # Ask question (retrieves from all sessions of this agent)
    answer = await system.ask("Where will we meet?")
    print(answer)  # Should mention Starbucks

    # Cleanup
    await system.close()

asyncio.run(main())
```

### Multi-Session Example

```python
import asyncio
import uuid
from ltm.simplemem import create_system

async def multi_session_example():
    agent_id = str(uuid.uuid4())
    system = await create_system(agent_id=agent_id)

    # Session 1
    session1 = str(uuid.uuid4())
    await system.add_dialogue(session1, "User", "Project deadline is Friday")
    await system.finalize(session1)

    # Session 2 (can access Session 1's memories)
    session2 = str(uuid.uuid4())
    await system.add_dialogue(session2, "User", "What's the deadline?")
    await system.finalize(session2)

    # Cross-session retrieval
    answer = await system.ask("When is the project deadline?")
    print(answer)  # Should answer "Friday"

    await system.close()

asyncio.run(multi_session_example())
```

### Agent Isolation Example

```python
import asyncio
import uuid
from ltm.simplemem import create_system

async def isolation_example():
    # Agent 1
    agent1_id = str(uuid.uuid4())
    agent1 = await create_system(agent_id=agent1_id)
    session1 = str(uuid.uuid4())
    await agent1.add_dialogue(session1, "Alice", "My secret password is ABC123")
    await agent1.finalize(session1)

    # Agent 2 (isolated from Agent 1)
    agent2_id = str(uuid.uuid4())
    agent2 = await create_system(agent_id=agent2_id)

    # Agent 2 cannot access Agent 1's memories
    answer = await agent2.ask("What is Alice's password?")
    print(answer)  # Should NOT reveal the password

    await agent1.close()
    await agent2.close()

asyncio.run(isolation_example())
```

## API Reference

### `MultiAgentMemorySystem`

#### `__init__(agent_id, ...)`

Initialize system (not connected yet).

**Parameters:**
- `agent_id` (str): Agent UUID
- `api_key` (str, optional): OpenAI API key
- `model` (str, optional): LLM model name
- `base_url` (str, optional): API base URL
- `qdrant_url` (str, optional): Qdrant server URL
- `postgres_url` (str, optional): PostgreSQL connection URL
- Other LLM and retrieval parameters

#### `async initialize()`

Connect to databases and initialize components. Must be called before any operations.

#### `async add_dialogue(session_id, speaker, content, timestamp=None)`

Add a dialogue to a session.

#### `async finalize(session_id)`

Process remaining dialogues and store to Qdrant.

#### `async ask(question) -> str`

Ask a question and get an answer (retrieves from all sessions).

#### `async get_all_memories() -> List[MemoryEntry]`

Get all memory entries for this agent.

#### `async get_session_dialogues(session_id) -> List[Dict]`

Get all dialogues for a specific session.

#### `async get_all_sessions() -> List[str]`

Get all session IDs for this agent.

#### `async close()`

Close database connections.

### `create_system(agent_id, ...) -> MultiAgentMemorySystem`

Convenience function to create and initialize system in one call.

## Configuration

Configuration is loaded from environment variables (via `ltm/config.py`).

Key settings:
- `QDRANT_URL`: Qdrant server URL (default: `http://localhost:6333`)
- `POSTGRES_URL`: PostgreSQL connection string
- `OPENAI_API_KEY`: Your OpenAI API key
- `WINDOW_SIZE`: Dialogue window size for processing (default: 40)
- `ENABLE_PARALLEL_PROCESSING`: Enable parallel processing (default: True)
- `ENABLE_PLANNING`: Enable retrieval planning (default: True)
- `ENABLE_REFLECTION`: Enable reflection-based retrieval (default: True)

See `ltm/config.py` for all configuration options.

## Architecture

```
ltm/
├── __init__.py              # Main entry point
├── simplemem.py            # MultiAgentMemorySystem class
├── config.py               # Configuration
├── core/                   # Core processing modules
│   ├── memory_builder.py   # Stage 1 & 2: Compression
│   ├── hybrid_retriever.py # Stage 3: Retrieval
│   └── answer_generator.py # Answer generation
├── database/               # Database layer
│   ├── vector_store.py     # Qdrant operations
│   ├── pg_store.py         # PostgreSQL operations
│   └── migrations/         # SQL schemas
├── models/                 # Data models
│   └── memory_entry.py     # MemoryEntry & Dialogue
└── utils/                  # Utilities
    ├── llm_client.py       # LLM client
    └── embedding.py        # Embedding model
```

## Database Schema

### PostgreSQL: `dialogues` Table

Stores raw dialogues with agent and session tracking.

### Qdrant: `simplemem_memories` Collection

Stores compressed memory entries with:
- Vector embeddings (1024 dimensions)
- Multi-view metadata (keywords, entities, persons, etc.)
- Agent ID for isolation
- Session ID for provenance

## Troubleshooting

### Import Errors

Make sure all dependencies are installed:
```bash
pip install -r ltm/DEPENDENCIES.txt
```

### Connection Errors

Verify databases are running:
```bash
# Check Qdrant
curl http://localhost:6333/collections

# Check PostgreSQL
psql -h localhost -U simplemem -d simplemem -c "SELECT 1"
```

### Memory Not Retrieved

Ensure `finalize()` was called after adding dialogues.

## License

Same as SimpleMem project license.
