"""
Configuration file - System parameters and LLM settings

IMPORTANT:
1. Configure your settings below OR use .env file
2. Environment variables override values in this file
3. Never commit .env to version control (it contains your API key)
"""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ============================================================================
# LLM Configuration
# ============================================================================

# OpenAI API Key (required)
# Get your key from: https://platform.openai.com/api-keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-api-key-here")

# Custom OpenAI Base URL (optional)
# Set to None to use default OpenAI endpoint
# Examples:
#   - Qwen/Alibaba: "https://dashscope.aliyuncs.com/compatible-mode/v1"
#   - Azure OpenAI: "https://YOUR-RESOURCE.openai.azure.com/openai/deployments/YOUR-DEPLOYMENT"
#   - Local server: "http://localhost:8000/v1"
#   - OpenAI (default): None
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "http://192.168.1.252:8601/v1")

# LLM Model name
# Examples: "gpt-4.1-mini", "gpt-4.1", "qwen3-max", "qwen-plus-2025-07-28"
LLM_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

# Embedding model (local, no API needed)
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
EMBEDDING_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "1024"))  # For Qwen3: up to 1024, supports 32-1024
EMBEDDING_CONTEXT_LENGTH = int(os.getenv("EMBEDDING_CONTEXT_LENGTH", "32768"))  # Qwen3 supports 32k context


# ============================================================================
# Advanced LLM Features
# ============================================================================

# Enable deep thinking mode (for Qwen and compatible models)
# Adds extra_body={"enable_thinking": True} to API calls
# Set to False for OpenAI models (they don't support this)
ENABLE_THINKING = os.getenv("ENABLE_THINKING", "true").lower() == "true"

# Enable streaming responses (outputs content as it's generated)
USE_STREAMING = os.getenv("USE_STREAMING", "true").lower() == "true"

# Enable JSON format mode (ensures LLM outputs valid JSON)
# Adds response_format={"type": "json_object"} to API calls
# Helps prevent parsing failures from extra text like ```json
USE_JSON_FORMAT = os.getenv("USE_JSON_FORMAT", "false").lower() == "true"


# ============================================================================
# Memory Building Parameters
# ============================================================================

# Number of dialogues per window (for locomo; for other dataset, please finetune it)
WINDOW_SIZE = int(os.getenv("WINDOW_SIZE", "40"))

# Window overlap size (for context continuity)
OVERLAP_SIZE = int(os.getenv("OVERLAP_SIZE", "2"))


# ============================================================================
# Retrieval Parameters (can be adjusted to balance between token usage and performance)
# ============================================================================

# Max entries returned by semantic search (vector similarity)
SEMANTIC_TOP_K = int(os.getenv("SEMANTIC_TOP_K", "25"))

# Max entries returned by keyword search (BM25 matching)
KEYWORD_TOP_K = int(os.getenv("KEYWORD_TOP_K", "5"))

# Max entries returned by structured search (metadata filtering)
STRUCTURED_TOP_K = int(os.getenv("STRUCTURED_TOP_K", "5"))


# ============================================================================
# Database Configuration
# ============================================================================

# [DEPRECATED] LanceDB Configuration (replaced by Qdrant)
# Path to LanceDB storage
LANCEDB_PATH = os.getenv("LANCEDB_PATH", "./lancedb_data")

# Memory table name
MEMORY_TABLE_NAME = os.getenv("MEMORY_TABLE_NAME", "memory_entries")


# ============================================================================
# Qdrant Vector Database Configuration
# ============================================================================

# Qdrant server URL
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")

# Qdrant API Key (optional, for production security)
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", None)

# Qdrant collection name
QDRANT_COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "simplemem_memories")


# ============================================================================
# PostgreSQL Database Configuration
# ============================================================================

# PostgreSQL connection settings
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTGRES_USER", "simplemem")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "simplemem")
POSTGRES_DB = os.getenv("POSTGRES_DB", "simplemem")

# Auto-generated connection URL (or use POSTGRES_URL directly from env)
POSTGRES_URL = os.getenv("POSTGRES_URL", f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}")



# ============================================================================
# Parallel Processing Configuration
# ============================================================================

# Memory Building Parallel Processing
ENABLE_PARALLEL_PROCESSING = os.getenv("ENABLE_PARALLEL_PROCESSING", "true").lower() == "true"
MAX_PARALLEL_WORKERS = int(os.getenv("MAX_PARALLEL_WORKERS", "16"))  # Number of parallel workers for memory building

# Retrieval Parallel Processing
ENABLE_PARALLEL_RETRIEVAL = os.getenv("ENABLE_PARALLEL_RETRIEVAL", "true").lower() == "true"
MAX_RETRIEVAL_WORKERS = int(os.getenv("MAX_RETRIEVAL_WORKERS", "8"))  # Number of parallel workers for retrieval queries

# Planning and Reflection Configuration
ENABLE_PLANNING = os.getenv("ENABLE_PLANNING", "true").lower() == "true"
ENABLE_REFLECTION = os.getenv("ENABLE_REFLECTION", "true").lower() == "true"
MAX_REFLECTION_ROUNDS = int(os.getenv("MAX_REFLECTION_ROUNDS", "2"))


# ============================================================================
# LLM-as-Judge Configuration (not used yet)
# ============================================================================

# Judge LLM API Key (optional - if None, uses OPENAI_API_KEY)
JUDGE_API_KEY = "your api-key here"

# Judge LLM Base URL (optional - if None, uses OPENAI_BASE_URL)
# Example: Use cheaper endpoint for evaluation
JUDGE_BASE_URL = "https://api.openai.com/v1/"

# Judge LLM Model (optional - if None, uses LLM_MODEL)
JUDGE_MODEL = "gpt-4.1-mini"

# Judge specific settings
JUDGE_ENABLE_THINKING = False  # Usually false for evaluation tasks
JUDGE_USE_STREAMING = False    # Usually false for evaluation
JUDGE_TEMPERATURE = 0.3        

# Example configurations:
# 1. Use cheaper model for judge evaluation:
#    JUDGE_MODEL = "gpt-4.1-mini"
#
# 2. Use different API provider for judge:
#    JUDGE_API_KEY = "your-judge-api-key"
#    JUDGE_BASE_URL = "https://api.different-provider.com/v1"
#    JUDGE_MODEL = "different-provider-model"
#
# 3. Use Qwen for judge (if available):
#    JUDGE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
#    JUDGE_MODEL = "qwen-plus-2025-09-11"

