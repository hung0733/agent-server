import os
import aiohttp
from typing import List, Union, Optional
from dotenv import load_dotenv

load_dotenv()


class EmbeddingAgent:
    """Embedding 和 Rerank 代理
    
    使用 Hugging Face Text Embeddings Inference (TEI) 服務
    配置通過環境變量設置：
    - EMBEDDING_ENDPOINT: Embedding API endpoint
    - RERANK_ENDPOINT: Rerank API endpoint
    """
    
    def __init__(
        self,
        embedding_endpoint: Optional[str] = None,
        rerank_endpoint: Optional[str] = None
    ):
        """初始化 EmbeddingAgent
        
        Args:
            embedding_endpoint: Embedding API 的 endpoint，如果為 None 則從環境變量讀取
            rerank_endpoint: Rerank API 的 endpoint，如果為 None 則從環境變量讀取
        """
        self.embedding_endpoint = embedding_endpoint or os.getenv("EMBEDDING_ENDPOINT", "http://localhost:8605")
        self.rerank_endpoint = rerank_endpoint or os.getenv("RERANK_ENDPOINT", "http://localhost:8606")
        
        # 移除末尾的斜線
        self.embedding_endpoint = self.embedding_endpoint.rstrip("/")
        self.rerank_endpoint = self.rerank_endpoint.rstrip("/")
        
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """獲取或創建 aiohttp session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def _embed_single(self, text: str, normalize: bool = True, pooling: str = "cls") -> List[float]:
        """內部方法：將單個文本轉換為向量
        
        使用 OpenAI 兼容格式：/v1/embeddings
        """
        session = await self._get_session()
        
        url = f"{self.embedding_endpoint}/v1/embeddings"
        
        # 確保文本正確編碼為 UTF-8
        text_bytes = text.encode('utf-8').decode('utf-8')
        
        # OpenAI 兼容格式
        payload = {
            "input": text_bytes,
            "model": "bge-m3"
        }
        
        import json
        async with session.post(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers={"Content-Type": "application/json; charset=utf-8"}) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Embedding API error: {response.status} - {error_text}")
            
            result = await response.json()
        
        # OpenAI 格式返回：{"data": [{"embedding": [...], "index": 0, "object": "embedding"}], ...}
        if "data" in result and len(result["data"]) > 0:
            return result["data"][0]["embedding"]
        return []
    
    async def _embed_batch(self, texts: List[str], normalize: bool = True, pooling: str = "cls") -> List[List[float]]:
        """內部方法：將文本列表轉換為向量
        
        使用 OpenAI 兼容格式：/v1/embeddings
        """
        session = await self._get_session()
        
        url = f"{self.embedding_endpoint}/v1/embeddings"
        
        # 確保所有文本正確編碼為 UTF-8
        texts_bytes = [t.encode('utf-8').decode('utf-8') for t in texts]
        
        # OpenAI 兼容格式
        payload = {
            "input": texts_bytes,
            "model": "bge-m3"
        }
        
        import json
        async with session.post(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers={"Content-Type": "application/json; charset=utf-8"}) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Embedding API error: {response.status} - {error_text}")
            
            result = await response.json()
        
        # OpenAI 格式返回：{"data": [{"embedding": [...], "index": 0, "object": "embedding"}], ...}
        if "data" in result:
            # 按 index 排序以確保順序正確
            embeddings = sorted(result["data"], key=lambda x: x["index"])
            return [item["embedding"] for item in embeddings]
        return []
    
    async def embed(
        self,
        texts: Union[str, List[str]],
        normalize: bool = True,
        pooling: str = "cls"
    ) -> Union[List[float], List[List[float]]]:
        """將文本轉換為向量
        
        Args:
            texts: 單個文本或文本列表
            normalize: 是否標準化向量（默認為 True）
            pooling: pooling 策略，可選 "cls" 或 "mean"
            
        Returns:
            單個向量或向量列表
            
        Example:
            >>> agent = EmbeddingAgent()
            >>> embedding = await agent.embed("Hello world")
            >>> embeddings = await agent.embed(["Hello", "World"])
        """
        if isinstance(texts, str):
            return await self._embed_single(texts, normalize, pooling)
        else:
            return await self._embed_batch(texts, normalize, pooling)
    
    async def embed_query(self, query: str) -> List[float]:
        """將查詢文本轉換為向量
        
        Args:
            query: 查詢文本
            
        Returns:
            查詢向量
        """
        return await self._embed_single(query)
    
    async def embed_documents(self, documents: List[str]) -> List[List[float]]:
        """將文檔列表轉換為向量
        
        Args:
            documents: 文檔列表
            
        Returns:
            文檔向量列表
        """
        return await self._embed_batch(documents)
    
    async def rerank(
        self,
        query: str,
        documents: List[str],
        top_n: Optional[int] = None,
        return_scores: bool = True
    ) -> Union[List[int], List[tuple]]:
        """重新排序文檔
        
        使用 Rerank API 對文檔進行相關性排序
        使用 OpenAI 兼容格式：/v1/rerank
        
        Args:
            query: 查詢文本
            documents: 待排序的文檔列表
            top_n: 返回前 N 個結果，如果為 None 則返回所有
            return_scores: 是否返回分數（默認為 True）
            
        Returns:
            如果 return_scores 為 True，返回 (索引，分數) 元組列表
            否則返回排序後的索引列表
            
        Example:
            >>> agent = EmbeddingAgent()
            >>> query = "機器學習"
            >>> docs = ["深度學習", "烹飪食譜", "神經網絡"]
            >>> results = await agent.rerank(query, docs, top_n=2)
            >>> print(results)  # [(0, 0.95), (2, 0.87)]
        """
        session = await self._get_session()
        
        url = f"{self.rerank_endpoint}/v1/rerank"
        
        # 確保所有文本正確編碼為 UTF-8
        query_bytes = query.encode('utf-8').decode('utf-8')
        documents_bytes = [d.encode('utf-8').decode('utf-8') for d in documents]
        
        # OpenAI 兼容格式
        payload = {
            "model": "bge-reranker-v2-m3",
            "query": query_bytes,
            "documents": documents_bytes,
            "top_n": top_n if top_n is not None else len(documents)
        }
        
        import json
        async with session.post(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers={"Content-Type": "application/json; charset=utf-8"}) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Rerank API error: {response.status} - {error_text}")
            
            result = await response.json()
        
        # 調試：打印原始響應
        # print(f"[DEBUG] Rerank API 原始響應：{result}")
        
        ranked_results = []
        if "results" in result:
            for item in result["results"]:
                idx = item.get("index", 0)
                score = item.get("relevance_score", 0.0)
                ranked_results.append((idx, score))
        
        # 按分數降序排序（如果 API 未排序）
        ranked_results.sort(key=lambda x: x[1], reverse=True)
        
        if not return_scores:
            return [idx for idx, _ in ranked_results]
        
        return ranked_results
    
    async def similarity_search(
        self,
        query: str,
        documents: List[str],
        document_embeddings: List[List[float]],
        top_n: int = 5,
        threshold: float = 0.0
    ) -> List[tuple]:
        """使用餘弦相似度進行相似度搜索
        
        Args:
            query: 查詢文本
            documents: 文檔列表
            document_embeddings: 文檔向量列表
            top_n: 返回最相似的 N 個結果
            threshold: 相似度閾值
            
        Returns:
            (索引，文檔，相似度分數) 元組列表
        """
        import math
        
        # 獲取查詢向量
        query_embedding = await self.embed_query(query)
        
        # 計算餘弦相似度
        def cosine_similarity(a: List[float], b: List[float]) -> float:
            dot_product = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot_product / (norm_a * norm_b)
        
        similarities = []
        for idx, (doc, emb) in enumerate(zip(documents, document_embeddings)):
            sim = cosine_similarity(query_embedding, emb)
            if sim >= threshold:
                similarities.append((idx, doc, sim))
        
        # 按相似度降序排序
        similarities.sort(key=lambda x: x[2], reverse=True)
        
        return similarities[:top_n]
    
    async def close(self):
        """關閉 aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def __aenter__(self):
        """Async context manager entry"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()
