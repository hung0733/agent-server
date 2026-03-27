"""Unit tests for EmbeddingModel — API mode and local fallback."""
import importlib
import importlib.util
import sys
import os
import numpy as np
import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Module loading helpers
# ---------------------------------------------------------------------------

def _load_embedding_module():
    """Import src.ltm.utils.embedding directly, bypassing src/ltm/__init__.py.

    The ltm package __init__ imports heavy optional dependencies (dateparser,
    etc.) that are not installed in the test environment.  We load just the
    embedding sub-module without executing any package __init__ files.
    """
    mod_name = "src.ltm.utils.embedding"
    if mod_name in sys.modules:
        return sys.modules[mod_name]

    # Register stub packages so Python doesn't try to run their __init__.py.
    for pkg in ("src", "src.ltm", "src.ltm.utils"):
        if pkg not in sys.modules:
            spec = importlib.util.find_spec(pkg)
            if spec is not None:
                stub = importlib.util.module_from_spec(spec)
                stub.__path__ = spec.submodule_search_locations
                stub.__package__ = pkg
                sys.modules[pkg] = stub

    spec = importlib.util.find_spec(mod_name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load the module once at collection time so we can reference it in patches.
_emb_mod = _load_embedding_module()
EmbeddingModel = _emb_mod.EmbeddingModel


def _make_api_model(endpoint="http://localhost:8605", model="test-model",
                    api_key="key", dimension=8):
    """Instantiate EmbeddingModel in API mode with fully patched module globals."""
    with patch.object(_emb_mod, "_ENDPOINT", endpoint), \
         patch.object(_emb_mod, "_MODEL", model), \
         patch.object(_emb_mod, "_API_KEY", api_key), \
         patch.object(_emb_mod, "_DIMENSION", dimension):
        instance = EmbeddingModel()
    return instance


# ---------------------------------------------------------------------------
# API-mode tests
# ---------------------------------------------------------------------------

class TestEmbeddingModelAPIMode:
    def test_init_uses_api_when_endpoint_set(self):
        """EmbeddingModel should enter API mode when EMBEDDING_LLM_ENDPOINT is set."""
        model = _make_api_model(endpoint="http://localhost:8605", dimension=8)
        assert model.model_type == "api"
        assert model.dimension == 8
        assert model._endpoint_url == "http://localhost:8605/v1/embeddings"

    def test_encode_calls_api_endpoint(self):
        """encode() in API mode should POST to /v1/embeddings and return numpy array."""
        model = _make_api_model(endpoint="http://localhost:8605", dimension=4)

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
        model = _make_api_model(endpoint="http://localhost:8605", dimension=4)

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
        model = _make_api_model(endpoint="http://localhost:8605", dimension=2)

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
        model = _make_api_model(endpoint="http://localhost:8605", dimension=2)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1, 0.2]}]
        }
        mock_response.raise_for_status = MagicMock()
        model._requests = MagicMock()
        model._requests.post.return_value = mock_response

        result = model.encode("bare string")
        assert result.shape == (1, 2)


# ---------------------------------------------------------------------------
# Local SentenceTransformer fallback tests
# ---------------------------------------------------------------------------

class TestEmbeddingModelLocalFallback:
    def test_no_endpoint_uses_sentence_transformer(self):
        """Without EMBEDDING_LLM_ENDPOINT, model_type should be 'sentence_transformer'."""
        mock_st_instance = MagicMock()
        mock_st_instance.get_sentence_embedding_dimension.return_value = 384
        mock_st_class = MagicMock(return_value=mock_st_instance)

        # sentence_transformers is not installed; inject a mock module so the
        # import inside _init_standard_sentence_transformer succeeds.
        mock_st_module = MagicMock()
        mock_st_module.SentenceTransformer = mock_st_class

        with patch.object(_emb_mod, "_ENDPOINT", None), \
             patch.object(_emb_mod, "_MODEL", "sentence-transformers/all-MiniLM-L6-v2"), \
             patch.dict(sys.modules, {"sentence_transformers": mock_st_module}):
            model = EmbeddingModel()

        assert model.model_type == "sentence_transformer"
        assert model.dimension == 384
