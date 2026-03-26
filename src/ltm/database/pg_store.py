"""
PostgreSQL Store - 管理 dialogues 表
Multi-Agent Memory System 的對話存儲層
"""
import asyncpg
from typing import List, Dict, Optional
from datetime import datetime


class PostgreSQLStore:
    """
    PostgreSQL 操作封裝
    
    負責管理原始對話記錄的持久化
    """
    
    def __init__(self, pool: asyncpg.Pool):
        """
        初始化 PostgreSQL Store
        
        Args:
            pool: asyncpg connection pool
        """
        self.pool = pool
    
    async def add_dialogue(
        self,
        agent_id: str,
        session_id: str,
        speaker: str,
        content: str,
        timestamp: Optional[str] = None
    ) -> int:
        """
        新增對話記錄
        
        Args:
            agent_id: Agent UUID
            session_id: Session UUID
            speaker: 發言者名稱
            content: 對話內容
            timestamp: ISO 8601 時間戳 (可選)
            
        Returns:
            dialogue_id: 插入的記錄 ID
        """
        # 轉換 timestamp
        ts = None
        if timestamp:
            try:
                ts = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except Exception as e:
                print(f"Warning: Failed to parse timestamp '{timestamp}': {e}")
        
        query = """
            INSERT INTO dialogues (agent_id, session_id, speaker, content, timestamp)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING dialogue_id
        """
        
        async with self.pool.acquire() as conn:
            dialogue_id = await conn.fetchval(
                query, agent_id, session_id, speaker, content, ts
            )
        
        return dialogue_id
    
    async def get_dialogues(
        self,
        agent_id: str,
        session_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        獲取對話記錄
        
        Args:
            agent_id: Agent UUID
            session_id: Session UUID (可選，如果提供則只返回該 session)
            limit: 限制返回數量 (可選)
            
        Returns:
            List of dialogue dicts
        """
        if session_id:
            query = """
                SELECT dialogue_id, speaker, content, timestamp, created_at
                FROM dialogues
                WHERE agent_id = $1 AND session_id = $2
                ORDER BY created_at ASC
            """
            args = [agent_id, session_id]
        else:
            query = """
                SELECT dialogue_id, session_id, speaker, content, timestamp, created_at
                FROM dialogues
                WHERE agent_id = $1
                ORDER BY created_at ASC
            """
            args = [agent_id]
        
        if limit:
            query += f" LIMIT {limit}"
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, *args)
        
        return [dict(row) for row in rows]
    
    async def get_sessions(self, agent_id: str) -> List[str]:
        """
        獲取 agent 的所有 session_ids
        
        Args:
            agent_id: Agent UUID
            
        Returns:
            List of session_id UUIDs (按創建時間倒序)
        """
        query = """
            SELECT DISTINCT session_id
            FROM dialogues
            WHERE agent_id = $1
            GROUP BY session_id
            ORDER BY MIN(created_at) DESC
        """
        
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, agent_id)
        
        return [str(row['session_id']) for row in rows]
    
    async def count_dialogues(
        self,
        agent_id: str,
        session_id: Optional[str] = None
    ) -> int:
        """
        統計對話數量
        
        Args:
            agent_id: Agent UUID
            session_id: Session UUID (可選)
            
        Returns:
            對話數量
        """
        if session_id:
            query = """
                SELECT COUNT(*) as count
                FROM dialogues
                WHERE agent_id = $1 AND session_id = $2
            """
            args = [agent_id, session_id]
        else:
            query = """
                SELECT COUNT(*) as count
                FROM dialogues
                WHERE agent_id = $1
            """
            args = [agent_id]
        
        async with self.pool.acquire() as conn:
            result = await conn.fetchval(query, *args)
        
        return result
