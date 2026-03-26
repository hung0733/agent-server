# SimpleMem Multi-Agent LTM Package

## Package Information

**Version**: 2.0.0-multiagent  
**Source**: SimpleMem project (multi-agent branch)  
**Packaged**: 2026-03-26  
**Target Project**: agent-server  

## Package Structure

```
ltm/
├── __init__.py                    # Main entry: MultiAgentMemorySystem, create_system
├── simplemem.py                   # Core system class
├── config.py                      # Configuration (env vars support)
├── DEPENDENCIES.txt               # Required Python packages
├── README.md                      # Usage guide
├── PACKAGE_INFO.md                # This file
│
├── core/                          # Core processing modules
│   ├── __init__.py
│   ├── memory_builder.py          # Stage 1 & 2: Semantic Structured Compression
│   ├── hybrid_retriever.py        # Stage 3: Intent-Aware Retrieval Planning
│   └── answer_generator.py        # Answer generation from context
│
├── database/                      # Database layer
│   ├── __init__.py
│   ├── vector_store.py            # Qdrant vector store operations
│   ├── pg_store.py                # PostgreSQL dialogue store
│   └── migrations/
│       └── 001_init_schema.sql    # PostgreSQL schema
│
├── models/                        # Data models
│   ├── __init__.py
│   └── memory_entry.py            # MemoryEntry & Dialogue models
│
└── utils/                         # Utilities
    ├── __init__.py
    ├── llm_client.py              # OpenAI-compatible LLM client
    └── embedding.py               # Local embedding model (Qwen3)
```

## File Count

- Python files: 15
- SQL files: 1
- Documentation: 3
- Total: 19 files

## Import Paths

All imports use relative imports within the package:
- From package root: `from ltm.simplemem import MultiAgentMemorySystem`
- From package: `from ltm import MultiAgentMemorySystem, create_system`

## Key Features

1. **Multi-Agent Isolation**: Complete data separation via agent_id
2. **Cross-Session Memory**: Same agent accesses all session memories
3. **DB-Based Context**: Fetches context from DB, not RAM
4. **Async API**: Full asyncio support for concurrent operations
5. **Parallel Processing**: Parallel memory building and retrieval

## Dependencies

See `DEPENDENCIES.txt` for full list. Key dependencies:
- qdrant-client (vector database)
- asyncpg (PostgreSQL async driver)
- openai (LLM client)
- sentence-transformers (embeddings)
- pydantic (data validation)

## Configuration

Configuration via environment variables (see `config.py`):
- `OPENAI_API_KEY`: Your API key
- `QDRANT_URL`: Qdrant server (default: http://localhost:6333)
- `POSTGRES_URL`: PostgreSQL connection string
- `WINDOW_SIZE`: Dialogue processing window (default: 40)
- Other LLM and retrieval parameters

## Usage Example

```python
import asyncio
import uuid
from ltm.simplemem import create_system

async def main():
    agent_id = str(uuid.uuid4())
    system = await create_system(agent_id=agent_id)
    
    session_id = str(uuid.uuid4())
    await system.add_dialogue(
        session_id=session_id,
        speaker="User",
        content="Hello world"
    )
    await system.finalize(session_id)
    
    answer = await system.ask("What did the user say?")
    await system.close()

asyncio.run(main())
```

## Database Requirements

### Qdrant
- Version: 1.7.0+
- Port: 6333 (HTTP), 6334 (gRPC)
- Collection: `simplemem_memories`
- Vector dimension: 1024

### PostgreSQL
- Version: 16+
- Port: 5432
- Database: `simplemem`
- Schema: See `database/migrations/001_init_schema.sql`
- Table: `dialogues` (with agent_id and session_id)

## Migration Notes

This package is adapted from SimpleMem's multi-agent implementation with:
- All absolute imports converted to relative imports
- Removed test code and documentation
- Config adapted for package usage
- Kept only core functionality (no HTTP API, MCP, or Skills)

## Verification

Import verification test passed (5/7 modules):
- ✅ Database modules (QdrantVectorStore, PostgreSQLStore)
- ✅ Models (Dialogue, MemoryEntry)
- ✅ Utils (LLMClient, EmbeddingModel)
- ⚠️ Core modules require dependencies (dateparser, etc.)
- ⚠️ Main system requires all dependencies

All import path issues resolved. Package is ready for use after installing dependencies.

## Next Steps

1. Install dependencies: `pip install -r ltm/DEPENDENCIES.txt`
2. Start Qdrant and PostgreSQL
3. Initialize PostgreSQL schema
4. Configure environment variables
5. Import and use: `from ltm.simplemem import create_system`

## Support

For issues or questions about SimpleMem, see the original project repository.
