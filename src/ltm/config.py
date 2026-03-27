"""
Configuration file for LTM (Long-Term Memory) module.

All settings are read from environment variables (.env file).
This module provides defaults and configuration constants for the SimpleMem system.
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# ============================================================================
# Database Configuration
# ============================================================================

# PostgreSQL connection settings (read from main project .env)
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "agentserver")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")
POSTGRES_DB = os.getenv("POSTGRES_DB", "agentserver")

# Auto-generated PostgreSQL connection URL
POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# SimpleMem schema name (for table isolation)
SIMPLEMEM_SCHEMA = os.getenv("SIMPLEMEM_SCHEMA", "simplemem")


# ============================================================================
# Qdrant Vector Database Configuration
# ============================================================================

# Qdrant connection settings (read from main project .env)
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))

# Auto-generated Qdrant URL
QDRANT_URL = os.getenv("QDRANT_URL", f"http://{QDRANT_HOST}:{QDRANT_PORT}")

# Qdrant API Key (optional, for production security)
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", None)

# Qdrant collection name for SimpleMem
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_LTM_COLLECTION", "simplemem_memories")


# ============================================================================
# LLM Features Configuration
# ============================================================================

# Enable deep thinking mode (for compatible models)
# Adds extra_body={"enable_thinking": True} to API calls
ENABLE_THINKING = os.getenv("LTM_ENABLE_THINKING", "false").lower() == "true"

# Enable streaming responses (outputs content as it's generated)
USE_STREAMING = os.getenv("LTM_USE_STREAMING", "false").lower() == "true"

# Enable JSON format mode (ensures LLM outputs valid JSON)
# Adds response_format={"type": "json_object"} to API calls
USE_JSON_FORMAT = os.getenv("LTM_USE_JSON_FORMAT", "true").lower() == "true"


# ============================================================================
# Memory Building Parameters
# ============================================================================

# Number of dialogues per window (for memory chunking)
WINDOW_SIZE = int(os.getenv("LTM_WINDOW_SIZE", "40"))


# ============================================================================
# Retrieval Parameters
# ============================================================================

# Max entries returned by semantic search (vector similarity)
SEMANTIC_TOP_K = int(os.getenv("LTM_SEMANTIC_TOP_K", "25"))

# Max entries returned by keyword search (BM25 matching)
KEYWORD_TOP_K = int(os.getenv("LTM_KEYWORD_TOP_K", "5"))

# Max entries returned by structured search (metadata filtering)
STRUCTURED_TOP_K = int(os.getenv("LTM_STRUCTURED_TOP_K", "5"))
