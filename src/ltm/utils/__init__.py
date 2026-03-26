"""
Utility modules for SimpleMem

- LLMClient: OpenAI-compatible LLM client
- EmbeddingModel: Local embedding model (Qwen3-Embedding)
"""

from .llm_client import LLMClient
from .embedding import EmbeddingModel

__all__ = ["LLMClient", "EmbeddingModel"]
