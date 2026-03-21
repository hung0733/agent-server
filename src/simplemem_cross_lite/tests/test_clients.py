"""Tests for LLMClient and EmbeddingClient with mocked HTTP responses."""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports (before conftest.py loads)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock

from clients.llm import LLMClient
from clients.embedding import EmbeddingClient


# =============================================================================
# LLMClient Tests
# =============================================================================


class TestLLMClientInitialization:
    """Test LLMClient initialization and configuration."""

    def test_init_with_defaults(self):
        """Test LLMClient initializes with default values."""
        client = LLMClient(api_key="test-key")
        
        assert client.api_key == "test-key"
        assert client.base_url == "https://api.openai.com/v1"
        assert client.model == "gpt-4o-mini"
        assert client._client is None

    def test_init_with_custom_values(self):
        """Test LLMClient initializes with custom values."""
        client = LLMClient(
            api_key="custom-key",
            base_url="https://custom.api.com/v1",
            model="custom-model",
        )
        
        assert client.api_key == "custom-key"
        assert client.base_url == "https://custom.api.com/v1"
        assert client.model == "custom-model"

    def test_init_strips_trailing_slash(self):
        """Test LLMClient strips trailing slash from base_url."""
        client = LLMClient(api_key="test-key", base_url="https://api.example.com/v1/")
        assert client.base_url == "https://api.example.com/v1"


class TestLLMClientChatCompletion:
    """Test LLMClient chat_completion method."""

    @pytest.mark.asyncio
    async def test_chat_completion_success(self):
        """Test successful chat completion response."""
        client = LLMClient(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Test response"}}]
        }
        mock_response.raise_for_status = MagicMock()
        
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(client, '_get_client', return_value=mock_client):
            result = await client.chat_completion(
                messages=[{"role": "user", "content": "Hello"}],
                temperature=0.5,
            )
        
        assert result == "Test response"
        mock_client.post.assert_called_once_with(
            "/chat/completions",
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "Hello"}],
                "temperature": 0.5,
            },
        )

    @pytest.mark.asyncio
    async def test_chat_completion_with_max_tokens(self):
        """Test chat completion includes max_tokens when provided."""
        client = LLMClient(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Test response"}}]
        }
        mock_response.raise_for_status = MagicMock()
        
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(client, '_get_client', return_value=mock_client):
            await client.chat_completion(
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=100,
            )
        
        call_json = mock_client.post.call_args[1]["json"]
        assert "max_tokens" in call_json
        assert call_json["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_chat_completion_with_response_format(self):
        """Test chat completion includes response_format when provided."""
        client = LLMClient(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"key": "value"}'}}]
        }
        mock_response.raise_for_status = MagicMock()
        
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(client, '_get_client', return_value=mock_client):
            await client.chat_completion(
                messages=[{"role": "user", "content": "Hello"}],
                response_format={"type": "json_object"},
            )
        
        call_json = mock_client.post.call_args[1]["json"]
        assert "response_format" in call_json
        assert call_json["response_format"] == {"type": "json_object"}

    @pytest.mark.asyncio
    async def test_chat_completion_http_error(self):
        """Test chat_completion raises on HTTP error."""
        client = LLMClient(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 500 Error")
        
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(client, '_get_client', return_value=mock_client):
            with pytest.raises(Exception, match="HTTP 500 Error"):
                await client.chat_completion(
                    messages=[{"role": "user", "content": "Hello"}],
                )

    @pytest.mark.asyncio
    async def test_chat_completion_creates_client_if_none(self):
        """Test chat_completion creates httpx client if not exists."""
        client = LLMClient(api_key="test-key")
        assert client._client is None
        
        with patch("httpx.AsyncClient") as mock_httpx_client:
            mock_instance = MagicMock()
            mock_httpx_client.return_value = mock_instance
            
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "choices": [{"message": {"content": "Test"}}]
            }
            mock_response.raise_for_status = MagicMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            
            await client.chat_completion(
                messages=[{"role": "user", "content": "Hello"}],
            )
            
            assert client._client is not None
            mock_httpx_client.assert_called_once()


class TestLLMClientExtractJSON:
    """Test LLMClient extract_json method."""

    def test_extract_json_valid_json(self):
        """Test extract_json parses valid JSON string."""
        client = LLMClient(api_key="test-key")
        text = '{"name": "test", "value": 123}'
        result = client.extract_json(text)
        assert result == {"name": "test", "value": 123}

    def test_extract_json_empty_string(self):
        """Test extract_json returns None for empty string."""
        client = LLMClient(api_key="test-key")
        result = client.extract_json("")
        assert result is None

    def test_extract_json_none(self):
        """Test extract_json returns None for None input."""
        client = LLMClient(api_key="test-key")
        result = client.extract_json(None)
        assert result is None

    def test_extract_json_json_block(self):
        """Test extract_json extracts JSON from markdown code block."""
        client = LLMClient(api_key="test-key")
        text = '''Here is the result:
```json
{"status": "success", "data": [1, 2, 3]}
```
Some more text.'''
        result = client.extract_json(text)
        assert result == {"status": "success", "data": [1, 2, 3]}

    def test_extract_json_generic_code_block(self):
        """Test extract_json extracts JSON from generic code block."""
        client = LLMClient(api_key="test-key")
        text = '''Result:
```
{"key": "value"}
```'''
        result = client.extract_json(text)
        assert result == {"key": "value"}

    def test_extract_json_bare_json(self):
        """Test extract_json extracts bare JSON from text."""
        client = LLMClient(api_key="test-key")
        text = 'Some text before {"key": "value"} some text after'
        result = client.extract_json(text)
        assert result == {"key": "value"}

    def test_extract_json_bare_array(self):
        """Test extract_json extracts bare JSON array from text."""
        client = LLMClient(api_key="test-key")
        text = "Here is the array: [1, 2, 3] end"
        result = client.extract_json(text)
        assert result == [1, 2, 3]

    def test_extract_json_with_prefix(self):
        """Test extract_json removes common prefixes."""
        client = LLMClient(api_key="test-key")
        text = "Here's the JSON: {\"result\": \"ok\"}"
        result = client.extract_json(text)
        assert result == {"result": "ok"}

    def test_extract_json_nested_objects(self):
        """Test extract_json handles nested objects."""
        client = LLMClient(api_key="test-key")
        text = '{"outer": {"inner": {"deep": "value"}}}'
        result = client.extract_json(text)
        assert result == {"outer": {"inner": {"deep": "value"}}}

    def test_extract_json_invalid_returns_none(self):
        """Test extract_json returns None for invalid JSON."""
        client = LLMClient(api_key="test-key")
        text = "This is not JSON at all"
        result = client.extract_json(text)
        assert result is None


class TestLLMClientClose:
    """Test LLMClient close method."""

    @pytest.mark.asyncio
    async def test_close_with_client(self):
        """Test close properly closes httpx client."""
        client = LLMClient(api_key="test-key")
        
        mock_httpx_client = MagicMock()
        mock_httpx_client.aclose = AsyncMock()
        client._client = mock_httpx_client
        
        await client.close()
        
        mock_httpx_client.aclose.assert_called_once()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_without_client(self):
        """Test close handles None client gracefully."""
        client = LLMClient(api_key="test-key")
        assert client._client is None
        
        await client.close()  # Should not raise
        assert client._client is None


# =============================================================================
# EmbeddingClient Tests
# =============================================================================


class TestEmbeddingClientInitialization:
    """Test EmbeddingClient initialization and configuration."""

    def test_init_with_defaults(self):
        """Test EmbeddingClient initializes with default values."""
        client = EmbeddingClient(api_key="test-key")
        
        assert client.api_key == "test-key"
        assert client.base_url == "https://api.openai.com/v1"
        assert client.model == "text-embedding-3-small"
        assert client._client is None

    def test_init_with_custom_values(self):
        """Test EmbeddingClient initializes with custom values."""
        client = EmbeddingClient(
            api_key="custom-key",
            base_url="https://custom.api.com/v1",
            model="custom-embedding-model",
        )
        
        assert client.api_key == "custom-key"
        assert client.base_url == "https://custom.api.com/v1"
        assert client.model == "custom-embedding-model"

    def test_init_strips_trailing_slash(self):
        """Test EmbeddingClient strips trailing slash from base_url."""
        client = EmbeddingClient(api_key="test-key", base_url="https://api.example.com/v1/")
        assert client.base_url == "https://api.example.com/v1"


class TestEmbeddingClientCreateEmbedding:
    """Test EmbeddingClient create_embedding method."""

    @pytest.mark.asyncio
    async def test_create_embedding_success(self):
        """Test successful embedding response."""
        client = EmbeddingClient(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(client, '_get_client', return_value=mock_client):
            result = await client.create_embedding(
                texts=["text1", "text2"],
            )
        
        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_client.post.assert_called_once_with(
            "/embeddings",
            json={
                "model": "text-embedding-3-small",
                "input": ["text1", "text2"],
            },
        )

    @pytest.mark.asyncio
    async def test_create_embedding_single_text(self):
        """Test create_embedding with single text."""
        client = EmbeddingClient(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(client, '_get_client', return_value=mock_client):
            result = await client.create_embedding(texts=["single text"])
        
        assert result == [[0.1, 0.2, 0.3]]

    @pytest.mark.asyncio
    async def test_create_embedding_sorts_by_index(self):
        """Test create_embedding sorts results by index."""
        client = EmbeddingClient(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"index": 2, "embedding": [0.7, 0.8, 0.9]},
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                {"index": 1, "embedding": [0.4, 0.5, 0.6]},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(client, '_get_client', return_value=mock_client):
            result = await client.create_embedding(texts=["a", "b", "c"])
        
        assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]]

    @pytest.mark.asyncio
    async def test_create_embedding_http_error(self):
        """Test create_embedding raises on HTTP error."""
        client = EmbeddingClient(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 401 Error")
        
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(client, '_get_client', return_value=mock_client):
            with pytest.raises(Exception, match="HTTP 401 Error"):
                await client.create_embedding(texts=["text"])

    @pytest.mark.asyncio
    async def test_create_embedding_creates_client_if_none(self):
        """Test create_embedding creates httpx client if not exists."""
        client = EmbeddingClient(api_key="test-key")
        assert client._client is None
        
        with patch("httpx.AsyncClient") as mock_httpx_client:
            mock_instance = MagicMock()
            mock_httpx_client.return_value = mock_instance
            
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]
            }
            mock_response.raise_for_status = MagicMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            
            await client.create_embedding(texts=["text"])
            
            assert client._client is not None
            mock_httpx_client.assert_called_once()


class TestEmbeddingClientCreateSingleEmbedding:
    """Test EmbeddingClient create_single_embedding method."""

    @pytest.mark.asyncio
    async def test_create_single_embedding_success(self):
        """Test successful single embedding response."""
        client = EmbeddingClient(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
            ]
        }
        mock_response.raise_for_status = MagicMock()
        
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(client, '_get_client', return_value=mock_client):
            result = await client.create_single_embedding(text="single text")
        
        assert result == [0.1, 0.2, 0.3]
        mock_client.post.assert_called_once_with(
            "/embeddings",
            json={
                "model": "text-embedding-3-small",
                "input": ["single text"],
            },
        )

    @pytest.mark.asyncio
    async def test_create_single_embedding_http_error(self):
        """Test create_single_embedding raises on HTTP error."""
        client = EmbeddingClient(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("HTTP 500 Error")
        
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(client, '_get_client', return_value=mock_client):
            with pytest.raises(Exception, match="HTTP 500 Error"):
                await client.create_single_embedding(text="text")


class TestEmbeddingClientClose:
    """Test EmbeddingClient close method."""

    @pytest.mark.asyncio
    async def test_close_with_client(self):
        """Test close properly closes httpx client."""
        client = EmbeddingClient(api_key="test-key")
        
        mock_httpx_client = MagicMock()
        mock_httpx_client.aclose = AsyncMock()
        client._client = mock_httpx_client
        
        await client.close()
        
        mock_httpx_client.aclose.assert_called_once()
        assert client._client is None

    @pytest.mark.asyncio
    async def test_close_without_client(self):
        """Test close handles None client gracefully."""
        client = EmbeddingClient(api_key="test-key")
        assert client._client is None
        
        await client.close()  # Should not raise
        assert client._client is None


# =============================================================================
# Integration-Style Tests (Client Lifecycle)
# =============================================================================


class TestClientLifecycle:
    """Test complete client lifecycle (create, use, close)."""

    @pytest.mark.asyncio
    async def test_llm_client_lifecycle(self):
        """Test complete LLMClient lifecycle."""
        client = LLMClient(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Response"}}]
        }
        mock_response.raise_for_status = MagicMock()
        
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(client, '_get_client', return_value=mock_client):
            # Use client
            result = await client.chat_completion(
                messages=[{"role": "user", "content": "Hello"}],
            )
            assert result == "Response"
            
            # Close client
            await client.close()
            assert client._client is None

    @pytest.mark.asyncio
    async def test_embedding_client_lifecycle(self):
        """Test complete EmbeddingClient lifecycle."""
        client = EmbeddingClient(api_key="test-key")
        
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]
        }
        mock_response.raise_for_status = MagicMock()
        
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        
        with patch.object(client, '_get_client', return_value=mock_client):
            # Use client
            result = await client.create_single_embedding(text="text")
            assert result == [0.1, 0.2, 0.3]
            
            # Close client
            await client.close()
            assert client._client is None
