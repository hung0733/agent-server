"""
Embedding utilities - Generate vector embeddings
Supports local SentenceTransformers or remote API endpoint (OpenAI-compatible)
"""
import os
from typing import List
import numpy as np
from dotenv import load_dotenv

from i18n import _

load_dotenv()

_ENDPOINT = os.getenv("EMBEDDING_LLM_ENDPOINT")
_API_KEY = os.getenv("EMBEDDING_LLM_API_KEY", "NO_KEY")
_MODEL = os.getenv("EMBEDDING_LLM_MODEL", "text-embedding-ada-002")
_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "2560"))


class EmbeddingModel:
    """
    Embedding model — uses remote API endpoint if EMBEDDING_LLM_ENDPOINT is set,
    otherwise falls back to local SentenceTransformers.
    """
    def __init__(self, model_name: str = None, use_optimization: bool = True):
        self.model_name = model_name or _MODEL
        self.use_optimization = use_optimization

        if _ENDPOINT:
            self._init_api_endpoint()
        elif self.model_name.startswith("qwen3"):
            self._init_qwen3_sentence_transformer()
        else:
            self._init_standard_sentence_transformer()

    # ------------------------------------------------------------------
    # Init methods
    # ------------------------------------------------------------------

    def _init_api_endpoint(self):
        """Use remote OpenAI-compatible embeddings endpoint."""
        import requests  # noqa: PLC0415 — lazy import, only needed in API mode
        self._requests = requests
        self._endpoint_url = f"{_ENDPOINT.rstrip('/')}/v1/embeddings"
        self._headers = {
            "Authorization": f"Bearer {_API_KEY}",
            "Content-Type": "application/json",
        }
        self.dimension = _DIMENSION
        self.model_type = "api"
        self.supports_query_prompt = False
        print(_(f"Embedding via API: {self._endpoint_url} model={self.model_name}"))

    def _init_qwen3_sentence_transformer(self):
        """Initialize Qwen3 model using SentenceTransformers."""
        try:
            from sentence_transformers import SentenceTransformer

            qwen3_models = {
                "qwen3-0.6b": "Qwen/Qwen3-Embedding-0.6B",
                "qwen3-4b": "Qwen/Qwen3-Embedding-4B",
                "qwen3-8b": "Qwen/Qwen3-Embedding-8B",
            }
            model_path = qwen3_models.get(self.model_name, self.model_name)
            print(_(f"Loading Qwen3 model via SentenceTransformers: {model_path}"))

            if self.use_optimization:
                try:
                    self.model = SentenceTransformer(
                        model_path,
                        model_kwargs={
                            "attn_implementation": "flash_attention_2",
                            "device_map": "auto",
                        },
                        tokenizer_kwargs={"padding_side": "left"},
                        trust_remote_code=True,
                    )
                    print(_("Qwen3 loaded with flash_attention_2 optimization"))
                except Exception as e:
                    print(_(f"Flash attention failed ({e}), using standard loading..."))
                    self.model = SentenceTransformer(model_path, trust_remote_code=True)
            else:
                self.model = SentenceTransformer(model_path, trust_remote_code=True)

            self.dimension = self.model.get_sentence_embedding_dimension()
            self.model_type = "qwen3_sentence_transformer"
            self.supports_query_prompt = hasattr(self.model, "prompts") and "query" in getattr(self.model, "prompts", {})
            print(_(f"Qwen3 model loaded successfully with dimension: {self.dimension}"))
        except Exception as e:
            print(_(f"Failed to load Qwen3 model: {e}"))
            print(_("Falling back to default SentenceTransformers model..."))
            self._fallback_to_sentence_transformer()

    def _init_standard_sentence_transformer(self):
        """Initialize standard SentenceTransformer model."""
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.model_name)
            self.dimension = self.model.get_sentence_embedding_dimension()
            self.model_type = "sentence_transformer"
            self.supports_query_prompt = False
            print(_(f"SentenceTransformer model loaded with dimension: {self.dimension}"))
        except Exception as e:
            print(_(f"Failed to load SentenceTransformer model: {e}"))
            raise

    def _fallback_to_sentence_transformer(self):
        """Fallback to a known-good SentenceTransformer model."""
        fallback_model = "sentence-transformers/all-MiniLM-L6-v2"
        print(_(f"Using fallback model: {fallback_model}"))
        self.model_name = fallback_model
        self._init_standard_sentence_transformer()

    # ------------------------------------------------------------------
    # Public encode methods
    # ------------------------------------------------------------------

    def encode(self, texts: List[str], is_query: bool = False) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]

        if self.model_type == "api":
            return self._encode_via_api(texts)
        if self.model_type == "qwen3_sentence_transformer" and self.supports_query_prompt and is_query:
            return self._encode_with_query_prompt(texts)
        return self._encode_standard(texts)

    def encode_single(self, text: str, is_query: bool = False) -> np.ndarray:
        return self.encode([text], is_query=is_query)[0]

    def encode_query(self, queries: List[str]) -> np.ndarray:
        return self.encode(queries, is_query=True)

    def encode_documents(self, documents: List[str]) -> np.ndarray:
        return self.encode(documents, is_query=False)

    # ------------------------------------------------------------------
    # Private encode helpers
    # ------------------------------------------------------------------

    def _encode_via_api(self, texts: List[str]) -> np.ndarray:
        """Call remote OpenAI-compatible /v1/embeddings endpoint."""
        payload = {"model": self.model_name, "input": texts}
        response = self._requests.post(
            self._endpoint_url,
            headers=self._headers,
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        vectors = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
        return np.array(vectors, dtype=np.float32)

    def _encode_with_query_prompt(self, texts: List[str]) -> np.ndarray:
        """Encode texts using Qwen3 query prompt."""
        try:
            return self.model.encode(
                texts,
                prompt_name="query",
                show_progress_bar=False,
                normalize_embeddings=True,
            )
        except Exception as e:
            print(_(f"Query prompt encoding failed: {e}, falling back to standard encoding"))
            return self._encode_standard(texts)

    def _encode_standard(self, texts: List[str]) -> np.ndarray:
        """Encode texts using standard SentenceTransformer method."""
        return self.model.encode(
            texts,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
