from typing import List, Optional


class EmbeddingClient:
    """OpenAI-compatible embedding client using httpx for async HTTP requests."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "text-embedding-3-small",
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def create_embedding(
        self,
        texts: List[str],
    ) -> List[List[float]]:
        """
        Create embeddings for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors (List[List[float]])
        """
        client = self._get_client()

        payload = {
            "model": self.model,
            "input": texts,
        }

        response = await client.post("/embeddings", json=payload)
        response.raise_for_status()
        data = response.json()

        # Sort by index to ensure correct order
        embeddings_data = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in embeddings_data]

    async def create_single_embedding(self, text: str) -> List[float]:
        """
        Create embedding for a single text.

        Args:
            text: Single text to embed

        Returns:
            Embedding vector (List[float])
        """
        embeddings = await self.create_embedding([text])
        return embeddings[0]
