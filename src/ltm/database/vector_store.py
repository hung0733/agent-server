"""
Qdrant Vector Store - Multi-View Indexing with Multi-Agent Support (Section 3.1)

Implements three-layer indexing I(m_k):
- Semantic Layer: s_k = E_dense(m_k) - Dense vector similarity
- Lexical Layer: l_k = E_sparse(m_k) - Full-text search  
- Symbolic Layer: r_k = E_sym(m_k) - Metadata filtering (SQL)

Multi-Agent Features:
- Agent isolation via agent_id payload filtering
- Cross-session memory sharing per agent
- Session tracking via session_id
"""
from typing import List, Optional, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
    SearchParams, OrderBy, Direction
)
from ..models.memory_entry import MemoryEntry
from ..utils.embedding import EmbeddingModel
from .. import config
import uuid


class QdrantVectorStore:
    """
    Qdrant Vector Store with Multi-Agent Isolation
    
    Features:
    - Single collection with agent_id payload filtering
    - Three-layer hybrid search (semantic + lexical + symbolic)
    - Cross-session memory sharing per agent
    - Context retrieval from DB (not RAM)
    """
    
    def __init__(
        self,
        client: QdrantClient,
        agent_id: str,
        embedding_model: EmbeddingModel = None,
        collection_name: str = None
    ):
        """
        初始化 Qdrant Vector Store
        
        Args:
            client: Qdrant client instance
            agent_id: Agent UUID for isolation
            embedding_model: Embedding model instance
            collection_name: Collection name (default from config)
        """
        self.client = client
        self.agent_id = agent_id
        self.embedding_model = embedding_model or EmbeddingModel()
        self.collection_name = collection_name or config.QDRANT_COLLECTION_NAME
        
        # Initialize collection
        self._init_collection()
    
    def _init_collection(self):
        """初始化 Qdrant collection（如果不存在）"""
        try:
            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]
            
            if self.collection_name not in collection_names:
                # Create collection
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.embedding_model.dimension,
                        distance=Distance.COSINE
                    )
                )
                
                # Create payload indexes for filtering
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="agent_id",
                    field_schema="keyword"
                )
                
                self.client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name="session_id",
                    field_schema="keyword"
                )
                
                print(f"✅ Created Qdrant collection: {self.collection_name}")
            else:
                print(f"✅ Using existing Qdrant collection: {self.collection_name}")
        
        except Exception as e:
            print(f"⚠️  Error initializing collection: {e}")
            raise
    
    def _entry_to_point(
        self, 
        entry: MemoryEntry, 
        vector: List[float]
    ) -> PointStruct:
        """
        Convert MemoryEntry to Qdrant Point
        
        Args:
            entry: MemoryEntry object
            vector: Embedding vector
            
        Returns:
            Qdrant PointStruct
        """
        return PointStruct(
            id=str(uuid.uuid4()),  # Qdrant point ID
            vector=vector,
            payload={
                "entry_id": entry.entry_id,
                "agent_id": entry.agent_id or self.agent_id,
                "session_id": entry.session_id,
                "lossless_restatement": entry.lossless_restatement,
                "keywords": entry.keywords,
                "timestamp": entry.timestamp or "",
                "location": entry.location or "",
                "persons": entry.persons,
                "entities": entry.entities,
                "topic": entry.topic or ""
            }
        )
    
    def _point_to_entry(self, point) -> MemoryEntry:
        """
        Convert Qdrant Point to MemoryEntry
        
        Args:
            point: Qdrant point object
            
        Returns:
            MemoryEntry object
        """
        payload = point.payload
        return MemoryEntry(
            entry_id=payload["entry_id"],
            agent_id=payload.get("agent_id"),
            session_id=payload.get("session_id"),
            lossless_restatement=payload["lossless_restatement"],
            keywords=payload.get("keywords", []),
            timestamp=payload.get("timestamp") or None,
            location=payload.get("location") or None,
            persons=payload.get("persons", []),
            entities=payload.get("entities", []),
            topic=payload.get("topic") or None
        )
    
    def add_entries(self, entries: List[MemoryEntry]):
        """
        批量添加 memory entries
        
        Args:
            entries: Memory entries to add
        """
        if not entries:
            return
        
        # 設置 agent_id (如果未設置)
        for entry in entries:
            if not entry.agent_id:
                entry.agent_id = self.agent_id
        
        # 生成 embeddings
        restatements = [entry.lossless_restatement for entry in entries]
        vectors = self.embedding_model.encode_documents(restatements)
        
        # 轉換成 Qdrant points
        points = [
            self._entry_to_point(entry, vector.tolist())
            for entry, vector in zip(entries, vectors)
        ]
        
        # 批量插入
        try:
            self.client.upsert(
                collection_name=self.collection_name,
                points=points
            )
            print(f"✅ Added {len(entries)} memory entries to Qdrant")
        except Exception as e:
            print(f"⚠️  Error adding entries: {e}")
            raise
    
    def get_recent_entries(
        self, 
        session_id: str, 
        limit: int = 3
    ) -> List[MemoryEntry]:
        """
        獲取當前 session 的最近 N 條記憶（用於上下文）
        
        **核心功能**: 替代 RAM 中的 previous_entries，從 DB 檲取上下文
        
        Args:
            session_id: Session UUID
            limit: 返回數量（默認 3）
            
        Returns:
            List of MemoryEntry (最新的在前)
        """
        try:
            # Scroll API 獲取該 session 的記憶
            results, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="agent_id",
                            match=MatchValue(value=self.agent_id)
                        ),
                        FieldCondition(
                            key="session_id",
                            match=MatchValue(value=session_id)
                        )
                    ]
                ),
                limit=limit * 2,  # 取多一點再排序
                with_payload=True,
                with_vectors=False
            )
            
            # 轉換並限制數量（Qdrant 的 point ID 是遞增的，所以越後面越新）
            entries = [self._point_to_entry(point) for point in results]
            
            # 取最後 N 條（最新的）
            recent_entries = entries[-limit:] if len(entries) > limit else entries
            recent_entries.reverse()  # 最新的在前
            
            return recent_entries
        
        except Exception as e:
            print(f"⚠️  Error fetching recent entries: {e}")
            return []
    
    def semantic_search(self, query: str, top_k: int = 5) -> List[MemoryEntry]:
        """
        Semantic Layer Search - Dense vector similarity
        自動過濾當前 agent_id
        
        Args:
            query: Search query
            top_k: Number of results
            
        Returns:
            List of MemoryEntry
        """
        try:
            # 生成 query embedding
            query_vector = self.embedding_model.encode_single(query, is_query=True)
            
            # 搜尋（自動過濾 agent_id）
            results = self.client.search(
                collection_name=self.collection_name,
                query_vector=query_vector.tolist(),
                query_filter=Filter(
                    must=[
                        FieldCondition(
                            key="agent_id",
                            match=MatchValue(value=self.agent_id)
                        )
                    ]
                ),
                limit=top_k
            )
            
            return [self._point_to_entry(point) for point in results]
        
        except Exception as e:
            print(f"⚠️  Error during semantic search: {e}")
            return []
    
    def keyword_search(self, keywords: List[str], top_k: int = 3) -> List[MemoryEntry]:
        """
        Lexical Layer Search - Keyword matching
        
        Note: Qdrant 的 full-text search 需要額外配置
        這裡使用簡化版本：通過 semantic search 實現
        
        Args:
            keywords: List of keywords
            top_k: Number of results
            
        Returns:
            List of MemoryEntry
        """
        try:
            if not keywords:
                return []
            
            # 用 keywords 組成 query，通過 semantic search
            query = " ".join(keywords)
            return self.semantic_search(query, top_k=top_k)
        
        except Exception as e:
            print(f"⚠️  Error during keyword search: {e}")
            return []
    
    def structured_search(
        self,
        persons: Optional[List[str]] = None,
        timestamp_range: Optional[tuple] = None,
        location: Optional[str] = None,
        entities: Optional[List[str]] = None,
        top_k: Optional[int] = 100
    ) -> List[MemoryEntry]:
        """
        Symbolic Layer Search - Metadata filtering
        
        Args:
            persons: List of person names
            timestamp_range: (start, end) tuple
            location: Location string
            entities: List of entities
            top_k: Maximum results
            
        Returns:
            List of MemoryEntry
        """
        try:
            if not any([persons, timestamp_range, location, entities]):
                return []
            
            # 構建 filter conditions
            must_conditions = [
                FieldCondition(
                    key="agent_id",
                    match=MatchValue(value=self.agent_id)
                )
            ]
            
            # TODO: 添加 persons, entities, location, timestamp 過濾
            # Qdrant 的 array/list filtering 需要特殊處理
            # 暫時使用 scroll 返回所有符合 agent_id 的結果
            
            # 使用 scroll API
            results, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(must=must_conditions),
                limit=top_k,
                with_payload=True,
                with_vectors=False
            )
            
            entries = [self._point_to_entry(point) for point in results]
            
            # 在 Python 層做額外過濾
            filtered = []
            for entry in entries:
                match = True
                
                if persons and not any(p in entry.persons for p in persons):
                    match = False
                
                if entities and not any(e in entry.entities for e in entities):
                    match = False
                
                if location and (not entry.location or location.lower() not in entry.location.lower()):
                    match = False
                
                # TODO: timestamp_range filtering
                
                if match:
                    filtered.append(entry)
            
            return filtered[:top_k]
        
        except Exception as e:
            print(f"⚠️  Error during structured search: {e}")
            return []
    
    def get_all_entries(self) -> List[MemoryEntry]:
        """
        獲取當前 agent 的所有 memory entries
        
        Returns:
            List of MemoryEntry
        """
        try:
            results, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="agent_id",
                            match=MatchValue(value=self.agent_id)
                        )
                    ]
                ),
                limit=10000,  # 限制最大返回數量
                with_payload=True,
                with_vectors=False
            )
            
            return [self._point_to_entry(point) for point in results]
        
        except Exception as e:
            print(f"⚠️  Error getting all entries: {e}")
            return []
    
    def clear(self):
        """
        清除當前 agent 的所有數據
        
        Note: Qdrant 不支援按 filter 刪除，需要先獲取所有 IDs
        """
        try:
            # 獲取所有該 agent 的 point IDs
            results, _ = self.client.scroll(
                collection_name=self.collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(
                            key="agent_id",
                            match=MatchValue(value=self.agent_id)
                        )
                    ]
                ),
                limit=10000,
                with_payload=False,
                with_vectors=False
            )
            
            point_ids = [point.id for point in results]
            
            if point_ids:
                self.client.delete(
                    collection_name=self.collection_name,
                    points_selector=point_ids
                )
                print(f"✅ Deleted {len(point_ids)} points for agent {self.agent_id}")
            else:
                print(f"ℹ️  No points to delete for agent {self.agent_id}")
        
        except Exception as e:
            print(f"⚠️  Error clearing data: {e}")
            raise
    
    def optimize(self):
        """
        Optimize collection (Qdrant handles this automatically)
        Kept for API compatibility
        """
        print("ℹ️  Qdrant handles optimization automatically")
        pass
    
    @staticmethod
    def query_multi_agent(
        client: QdrantClient,
        agent_ids: List[str],
        collection_name: str = None,
        limit: int = 100
    ) -> List[MemoryEntry]:
        """
        Query entries across multiple agents (for dashboard/aggregation).
        
        Args:
            client: QdrantClient instance
            agent_ids: List of agent IDs to query
            collection_name: Collection name (default from config)
            limit: Maximum entries per agent
            
        Returns:
            List of MemoryEntry across all specified agents
        """
        if not agent_ids:
            return []
        
        collection_name = collection_name or config.QDRANT_COLLECTION_NAME
        all_entries = []
        
        for agent_id in agent_ids:
            try:
                results, _ = client.scroll(
                    collection_name=collection_name,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="agent_id",
                                match=MatchValue(value=agent_id)
                            )
                        ]
                    ),
                    limit=limit,
                    with_payload=True,
                    with_vectors=False
                )
                
                for point in results:
                    payload = point.payload
                    entry = MemoryEntry(
                        entry_id=payload["entry_id"],
                        agent_id=payload.get("agent_id"),
                        session_id=payload.get("session_id"),
                        lossless_restatement=payload["lossless_restatement"],
                        keywords=payload.get("keywords", []),
                        timestamp=payload.get("timestamp") or None,
                        location=payload.get("location") or None,
                        persons=payload.get("persons", []),
                        entities=payload.get("entities", []),
                        topic=payload.get("topic") or None
                    )
                    all_entries.append(entry)
            
            except Exception as e:
                print(f"⚠️  Error querying agent {agent_id}: {e}")
                continue
        
        return all_entries


VectorStore = QdrantVectorStore
