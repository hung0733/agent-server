#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Long Term Memory Query Tool

功能：
1. 用戶輸入 keyword，按 Ctrl+D 發送
2. 將用戶輸入轉換為 vector
3. 去 long term memory table 用 Cosine Distance 找出最接近的 10-15 條
4. 將呢 10 幾條記憶連同用戶問題，一齊 send 去 Reranking
5. 攞 Reranker 計分再輸出 content 同分數，輸出計時
"""

import asyncio
import sys
import os
import time
import io
from typing import List, Dict, Any, Optional

# 添加項目根目錄到 Python 路徑
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 確保 stdin 使用 UTF-8 編碼
if sys.stdin.encoding != 'utf-8':
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from llm.embedding_agent import EmbeddingAgent
from db.long_term_memory_dao import LongTermMemoryDAO
from db.conn_pool import ConnPool
from sqlalchemy.ext.asyncio import AsyncSession
from agent.routing_agent import RoutingAgent


class LongTermMemoryQueryTool:
    """Long Term Memory 查詢工具"""
    
    def __init__(self, agent_id: int = 1):
        """初始化查詢工具
        
        Args:
            agent_id: Agent ID，用於過濾記憶
        """
        self.agent_id = agent_id
        self.embedding_agent = EmbeddingAgent()
        self.memory_dao = LongTermMemoryDAO()
        self.conn_pool = ConnPool()
        self.routing_agent = RoutingAgent()
    
    async def read_user_input(self) -> str:
        """讀取用戶輸入，支持 Ctrl+D 發送
        
        Returns:
            用戶輸入的文本
        """
        print("\n📝 請輸入查詢關鍵字（按 Ctrl+D 發送）：")
        print("-" * 50)
        
        lines = []
        try:
            while True:
                line = sys.stdin.readline()
                if not line:  # Ctrl+D 被按下
                    break
                # 確保字符串正確編碼
                line = line.rstrip('\n')
                if line:
                    lines.append(line)
        except KeyboardInterrupt:
            print("\n❌ 輸入被中斷")
            return ""
        except UnicodeDecodeError as e:
            print(f"\n❌ 編碼錯誤：{e}")
            return ""
        
        return '\n'.join(lines).strip()
    
    async def get_similar_memories(
        self,
        session: AsyncSession,
        query_vector: List[float],
        top_k: int = 15,
        similarity_threshold: float = 0.45
    ) -> List[Dict[str, Any]]:
        """獲取相似的記憶
        
        Args:
            session: 數據庫 session
            query_vector: 查詢向量
            top_k: 返回前 K 個結果
            similarity_threshold: 相似度閾值（預設 0.45）
            
        Returns:
            記憶列表
        """
        memories = await self.memory_dao.get_similar_memories(
            session=session,
            agent_id=self.agent_id,
            query_vector=query_vector,
            top_k=top_k,
            similarity_threshold=similarity_threshold
        )
        
        # 轉換為字典格式
        result = []
        for mem in memories:
            # content 是 JSON 格式，可能包含 'summary' 或其他字段
            content_text = ""
            if isinstance(mem.content, dict):
                content_text = mem.content.get('summary', str(mem.content))
            else:
                content_text = str(mem.content)
            
            # 處理 created_at 的轉換
            created_at_str = None
            if mem.created_at is not None:
                from datetime import datetime
                if isinstance(mem.created_at, datetime):
                    created_at_str = mem.created_at.isoformat()
                else:
                    created_at_str = str(mem.created_at)
            
            result.append({
                'id': mem.id,
                'content': content_text,
                'importance': mem.importance,
                'created_at': created_at_str,
                'vector_content': mem.vector_content
            })
        
        return result
    
    async def rerank_memories(
        self, 
        query: str, 
        memories: List[Dict[str, Any]]
    ) -> List[tuple]:
        """對記憶進行 reranking
        
        Args:
            query: 查詢文本
            memories: 記憶列表
            
        Returns:
            (索引，分數) 元組列表
        """
        # 提取記憶內容
        documents = [mem['content'] for mem in memories]
        
        if not documents:
            print("⚠️ 記憶列表為空，無法進行 reranking")
            return []
        
        # 使用 reranker 進行排序
        print(f"🔍 正在調用 rerank API，查詢：{query[:50]}...，文檔數量：{len(documents)}")
        try:
            results = await self.embedding_agent.rerank(
                query=query,
                documents=documents,
                top_n=None,  # 返回所有結果
                return_scores=True
            )
            print(f"📥 Rerank API 返回結果：{results}")
        except Exception as e:
            print(f"❌ Rerank API 調用失敗：{e}")
            return []
        
        # 確保返回類型一致
        if isinstance(results, list) and len(results) > 0 and not isinstance(results[0], tuple):
            # 如果返回的是索引列表，轉換為 (索引，0.0) 元組列表
            print(f"⚠️ Rerank 返回格式異常，轉換為元組列表")
            return [(idx, 0.0) for idx in results]
        
        if not results:
            print("⚠️ Rerank 返回空結果")
        
        return results  # type: ignore
    
    async def query(self, query_text: str) -> List[Dict[str, Any]]:
        """執行查詢
        
        Args:
            query_text: 查詢文本
            
        Returns:
            排序後的記憶列表，包含分數
        """
        if not query_text.strip():
            print("❌ 查詢文本為空")
            return []
        
        # 步驟 1: 使用 RoutingAgent 分析搜索關鍵字
        print("\n⏳ 正在使用 RoutingAgent 分析搜索關鍵字...")
        async with self.conn_pool.AsyncSessionLocal() as session:
            keyword = await self.routing_agent.analyse_search_keyword(
                session=session,
                user_input=query_text
            )
            print(f"✅ 關鍵字分析完成：{keyword}")
            
            # 步驟 2: 將關鍵字轉換為 vector
            print("\n⏳ 正在生成查詢向量...")
            query_vector = await self.embedding_agent.embed_query(keyword)
            print(f"✅ 向量生成完成，維度：{len(query_vector)}")
            
            # 步驟 3: 從數據庫獲取相似記憶（相似度 > 0.45）
            print(f"\n⏳ 正在從數據庫檢索最相似的記憶...（相似度 > 0.45）")
            similar_memories = await self.get_similar_memories(
                session=session,
                query_vector=query_vector,
                top_k=15,
                similarity_threshold=0.45
            )
        
        print(f"✅ 找到 {len(similar_memories)} 條相似記憶")
        
        if not similar_memories:
            print("⚠️ 未找到任何相似記憶")
            return []
        
        # 步驟 4: 對記憶進行 reranking（使用原始查詢文本）
        print("\n⏳ 正在進行 Reranking...")
        rerank_results = await self.rerank_memories(
            query=keyword,
            memories=similar_memories
        )
        print(f"✅ Reranking 完成")
        
        # 步驟 5: 組合結果
        final_results = []
        for idx, score in rerank_results:
            mem = similar_memories[idx]
            final_results.append({
                'rank': len(final_results) + 1,
                'id': mem['id'],
                'content': mem['content'],
                'score': score,
                'importance': mem['importance'],
                'created_at': mem['created_at']
            })
        
        return final_results
    
    async def run(self):
        """運行查詢工具"""
        print("=" * 60)
        print("🧠 Long Term Memory Query Tool")
        print("=" * 60)
        print(f"Agent ID: {self.agent_id}")
        print("提示：輸入關鍵字後按 Ctrl+D (Linux/Mac) 或 Ctrl+Z+Enter (Windows) 發送")
        
        # 讀取用戶輸入
        query_text = await self.read_user_input()
        
        if not query_text:
            return
        
        print(f"\n🔍 查詢：{query_text}")
        print("-" * 60)
        
        # 記錄開始時間
        start_time = time.time()
        
        # 執行查詢
        results = await self.query(query_text)
        
        # 記錄結束時間
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        # 輸出結果
        print("\n" + "=" * 60)
        print(f"📊 查詢結果（共 {len(results)} 條，耗時：{elapsed_time:.3f} 秒）")
        print("=" * 60)
        
        if not results:
            print("⚠️ 未找到相關記憶")
        else:
            for i, result in enumerate(results, 1):
                print(f"\n【Rank #{result['rank']}】")
                print(f"  ID: {result['id']}")
                print(f"  分數：{result['score']:.4f}")
                print(f"  重要性：{result['importance']}")
                print(f"  創建時間：{result['created_at']}")
                print(f"  內容：{result['content'][:200]}..." if len(result['content']) > 200 else f"  內容：{result['content']}")
        
        print("\n" + "=" * 60)
        print(f"⏱️  總耗時：{elapsed_time:.3f} 秒")
        print("=" * 60)
    
    async def close(self):
        """關閉資源"""
        await self.embedding_agent.close()
        await self.conn_pool.dispose()
        await self.routing_agent.close()


async def main():
    """主函數"""
    # 從命令行參數或環境變量獲取 agent_id
    agent_id = 1
    if len(sys.argv) > 1:
        try:
            agent_id = int(sys.argv[1])
        except ValueError:
            print(f"⚠️ 無效的 agent_id: {sys.argv[1]}，使用預設值 1")
    
    # 創建查詢工具
    query_tool = LongTermMemoryQueryTool(agent_id=agent_id)
    
    try:
        await query_tool.run()
    finally:
        await query_tool.close()


if __name__ == "__main__":
    asyncio.run(main())
