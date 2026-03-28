# EmbeddingModel Remote Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow `EmbeddingModel` to call a remote OpenAI-compatible embeddings API (e.g. llama.cpp serving qwen3-embedding-4b) instead of loading models locally, configured entirely via `.env`.

**Architecture:** `EmbeddingModel` reads `EMBEDDING_LLM_ENDPOINT`, `EMBEDDING_LLM_MODEL`, `EMBEDDING_LLM_API_KEY`, and `EMBEDDING_DIMENSION` directly from the environment at module load time. When `EMBEDDING_LLM_ENDPOINT` is set, all encode calls go to `POST {endpoint}/v1/embeddings`; otherwise the existing local SentenceTransformers path is used unchanged.

**Tech Stack:** Python 3.12, `requests`, `python-dotenv`, `numpy`, `sentence-transformers` (local path only)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/ltm/utils/embedding.py` | **Modify** | Core EmbeddingModel — add API mode, remove config.py import |
| `.env.example` | **Modify** | Document the four new env vars |
| `tests/unit/test_embedding.py` | **Create** | Unit tests for both API mode and local fallback |

---

### Task 1: Core changes to `embedding.py` ✅ (already applied)

> This task is complete. It is documented here for reference and verification.

**Files:**
- Modify: `src/ltm/utils/embedding.py`

- [x] **Step 1: Remove `config.py` import, add direct env reads at module top**

```python
import os
from dotenv import load_dotenv

load_dotenv()

_ENDPOINT = os.getenv("EMBEDDING_LLM_ENDPOINT")
_API_KEY  = os.getenv("EMBEDDING_LLM_API_KEY", "NO_KEY")
_MODEL    = os.getenv("EMBEDDING_LLM_MODEL", "text-embedding-ada-002")
_DIMENSION = int(os.getenv("EMBEDDING_DIMENSION", "2560"))
```

- [x] **Step 2: Add `_init_api_endpoint()` and `_encode_via_api()` methods**

```python
def _init_api_endpoint(self):
    import requests
    self._requests = requests
    self._endpoint_url = f"{_ENDPOINT.rstrip('/')}/v1/embeddings"
    self._headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
    }
    self.dimension = _DIMENSION
    self.model_type = "api"
    self.supports_query_prompt = False
    print(f"Embedding via API: {self._endpoint_url} model={self.model_name}")

def _encode_via_api(self, texts: List[str]) -> np.ndarray:
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
```

- [x] **Step 3: Route `encode()` through API when `model_type == "api"`**

```python
def encode(self, texts: List[str], is_query: bool = False) -> np.ndarray:
    if isinstance(texts, str):
        texts = [texts]
    if self.model_type == "api":
        return self._encode_via_api(texts)
    if self.model_type == "qwen3_sentence_transformer" and self.supports_query_prompt and is_query:
        return self._encode_with_query_prompt(texts)
    return self._encode_standard(texts)
```

- [x] **Step 4: Verify file looks correct**

```bash
python -c "import sys; sys.path.insert(0,'src'); from ltm.utils.embedding import EmbeddingModel; print('import OK')"
```

Expected output: `import OK` (no errors; model will NOT be loaded because we are not instantiating it)

---

### Task 2: Update `.env.example` ✅ (already applied)

**Files:**
- Modify: `.env.example`

- [x] **Step 1: Add embedding vars to `.env.example`**

```
# Embedding Model Configuration
# If EMBEDDING_LLM_ENDPOINT is set, uses remote OpenAI-compatible API; otherwise loads locally via SentenceTransformers
EMBEDDING_LLM_ENDPOINT=http://localhost:8605
EMBEDDING_LLM_API_KEY=NO_KEY
EMBEDDING_LLM_MODEL=qwen3-embedding-4b
EMBEDDING_DIMENSION=2560
```

---

### Task 3: Write unit tests for `EmbeddingModel`

**Files:**
- Create: `tests/unit/test_embedding.py`

- [ ] **Step 1: Write failing tests**

```python
"""Unit tests for EmbeddingModel — API mode and local fallback."""
import os
import numpy as np
import pytest
from unittest.mock import MagicMock, patch


def _import_embedding_model(endpoint=None, model="test-model", api_key="key", dimension="8"):
    """Re-import EmbeddingModel with patched env vars."""
    env = {
        "EMBEDDING_LLM_MODEL": model,
        "EMBEDDING_LLM_API_KEY": api_key,
        "EMBEDDING_DIMENSION": dimension,
    }
    if endpoint:
        env["EMBEDDING_LLM_ENDPOINT"] = endpoint

    # Patch env and re-import the module so module-level vars are re-evaluated
    import importlib
    import src.ltm.utils.embedding as emb_mod
    with patch.dict(os.environ, env, clear=False):
        # Force re-evaluation of module-level constants
        with patch("src.ltm.utils.embedding._ENDPOINT", endpoint), \
             patch("src.ltm.utils.embedding._MODEL", model), \
             patch("src.ltm.utils.embedding._API_KEY", api_key), \
             patch("src.ltm.utils.embedding._DIMENSION", int(dimension)):
            from src.ltm.utils.embedding import EmbeddingModel
            return EmbeddingModel


class TestEmbeddingModelAPIMode:
    def test_init_uses_api_when_endpoint_set(self):
        """EmbeddingModel should enter API mode when EMBEDDING_LLM_ENDPOINT is set."""
        EmbeddingModel = _import_embedding_model(endpoint="http://localhost:8605")
        model = EmbeddingModel()
        assert model.model_type == "api"
        assert model.dimension == 8
        assert model._endpoint_url == "http://localhost:8605/v1/embeddings"

    def test_encode_calls_api_endpoint(self):
        """encode() in API mode should POST to /v1/embeddings and return numpy array."""
        EmbeddingModel = _import_embedding_model(endpoint="http://localhost:8605", dimension="4")
        model = EmbeddingModel()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
                {"index": 1, "embedding": [0.5, 0.6, 0.7, 0.8]},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        model._requests = MagicMock()
        model._requests.post.return_value = mock_response

        result = model.encode(["hello", "world"])

        assert isinstance(result, np.ndarray)
        assert result.shape == (2, 4)
        np.testing.assert_array_almost_equal(result[0], [0.1, 0.2, 0.3, 0.4])
        model._requests.post.assert_called_once_with(
            "http://localhost:8605/v1/embeddings",
            headers={"Authorization": "Bearer key", "Content-Type": "application/json"},
            json={"model": "test-model", "input": ["hello", "world"]},
            timeout=60,
        )

    def test_encode_single_returns_1d_array(self):
        """encode_single() should return a 1-D vector."""
        EmbeddingModel = _import_embedding_model(endpoint="http://localhost:8605", dimension="4")
        model = EmbeddingModel()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]}]
        }
        mock_response.raise_for_status = MagicMock()
        model._requests = MagicMock()
        model._requests.post.return_value = mock_response

        result = model.encode_single("hello")

        assert result.ndim == 1
        assert result.shape == (4,)

    def test_results_ordered_by_index(self):
        """API response items out of order should be sorted by index."""
        EmbeddingModel = _import_embedding_model(endpoint="http://localhost:8605", dimension="2")
        model = EmbeddingModel()

        mock_response = MagicMock()
        # Return items in reverse order
        mock_response.json.return_value = {
            "data": [
                {"index": 1, "embedding": [0.9, 0.8]},
                {"index": 0, "embedding": [0.1, 0.2]},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        model._requests = MagicMock()
        model._requests.post.return_value = mock_response

        result = model.encode(["first", "second"])
        np.testing.assert_array_almost_equal(result[0], [0.1, 0.2])
        np.testing.assert_array_almost_equal(result[1], [0.9, 0.8])

    def test_string_input_wrapped_in_list(self):
        """Passing a bare string (not a list) should still work."""
        EmbeddingModel = _import_embedding_model(endpoint="http://localhost:8605", dimension="2")
        model = EmbeddingModel()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1, 0.2]}]
        }
        mock_response.raise_for_status = MagicMock()
        model._requests = MagicMock()
        model._requests.post.return_value = mock_response

        result = model.encode("bare string")
        assert result.shape == (1, 2)


class TestEmbeddingModelLocalFallback:
    def test_no_endpoint_uses_sentence_transformer(self):
        """Without EMBEDDING_LLM_ENDPOINT, model_type should NOT be 'api'."""
        with patch("src.ltm.utils.embedding._ENDPOINT", None):
            with patch("src.ltm.utils.embedding._MODEL", "sentence-transformers/all-MiniLM-L6-v2"):
                from src.ltm.utils.embedding import EmbeddingModel
                with patch("sentence_transformers.SentenceTransformer") as mock_st:
                    mock_instance = MagicMock()
                    mock_instance.get_sentence_embedding_dimension.return_value = 384
                    mock_st.return_value = mock_instance
                    model = EmbeddingModel()
                    assert model.model_type == "sentence_transformer"
                    assert model.dimension == 384
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /mnt/data/workspace/agent-server && source .venv/bin/activate && python -m pytest tests/unit/test_embedding.py -v 2>&1 | head -40
```

Expected: `ImportError` or `ModuleNotFoundError` — test file exists but module patching not yet wired.

- [ ] **Step 3: Run tests properly with sys.path set**

```bash
cd /mnt/data/workspace/agent-server && source .venv/bin/activate && PYTHONPATH=. python -m pytest tests/unit/test_embedding.py -v
```

Expected: All 5 tests PASS (the implementation was already applied in Task 1).

- [ ] **Step 4: Commit tests**

```bash
cd /mnt/data/workspace/agent-server
git add tests/unit/test_embedding.py
git commit -m "test(ltm): add unit tests for EmbeddingModel API mode"
```

---

### Task 4: Commit all prior changes

- [ ] **Step 1: Verify working tree**

```bash
cd /mnt/data/workspace/agent-server && git status
```

Expected: `src/ltm/utils/embedding.py` and `.env.example` shown as modified.

- [ ] **Step 2: Commit**

```bash
cd /mnt/data/workspace/agent-server
git add src/ltm/utils/embedding.py .env.example
git commit -m "feat(ltm): support remote OpenAI-compatible embedding endpoint via .env

Read EMBEDDING_LLM_ENDPOINT, EMBEDDING_LLM_MODEL, EMBEDDING_LLM_API_KEY,
and EMBEDDING_DIMENSION directly from .env; remove config.py dependency.
When endpoint is set, encode() calls POST /v1/embeddings instead of
loading a local SentenceTransformers model."
```

---

## Verification

After all tasks are complete, run:

```bash
cd /mnt/data/workspace/agent-server && source .venv/bin/activate && PYTHONPATH=. python -m pytest tests/unit/test_embedding.py -v
```

Expected output:
```
tests/unit/test_embedding.py::TestEmbeddingModelAPIMode::test_init_uses_api_when_endpoint_set PASSED
tests/unit/test_embedding.py::TestEmbeddingModelAPIMode::test_encode_calls_api_endpoint PASSED
tests/unit/test_embedding.py::TestEmbeddingModelAPIMode::test_encode_single_returns_1d_array PASSED
tests/unit/test_embedding.py::TestEmbeddingModelAPIMode::test_results_ordered_by_index PASSED
tests/unit/test_embedding.py::TestEmbeddingModelAPIMode::test_string_input_wrapped_in_list PASSED
tests/unit/test_embedding.py::TestEmbeddingModelLocalFallback::test_no_endpoint_uses_sentence_transformer PASSED
```
