import json
import os
import re
from typing import Any, Dict, List, Optional

from agent.agent import Agent
from db.agent_dao import AgentDAO
from db.conn_pool import ConnPool
from db.long_term_memory_dao import LongTermMemoryDAO
from db.memory_block_dao import MemoryBlockDAO
from db.message_dao import MessageDAO
from db.prompt_dao import PromptDAO
from dto.agent import AgentDTO
from dto.message import MessageDTO
from dto.prompt import PromptDTO
from dto.session import SessionDTO
from global_var import GlobalVar
from llm.brain_agent import BrainAgent
from llm.embedding_agent import EmbeddingAgent


class ArchiveGhost(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = BrainAgent(self.stream)
        self.embedding_agent = EmbeddingAgent()

    @classmethod
    async def get_agent(cls, agent_id: str, session_id: str):
        agent: Optional[AgentDTO] = None
        session: Optional[SessionDTO] = None

        agent, session = await Agent.get_db_agent(agent_id, session_id)

        if agent and session:
            # 攞到資料，返傳實例
            return cls(
                db_id=agent.id,  # type: ignore
                agent_id=agent.agent_id,  # type: ignore
                session_db_id=session.id,
                session_id=session.session_id,
                name=agent.name,  # type: ignore
                sys_prompt=agent.sys_prompt,  # type: ignore
                stream=True,
            )
        return None

    async def summary(self, msg_list: list[MessageDTO]):
        dto: PromptDTO
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            dto = PromptDTO.from_model(
                await PromptDAO().get_by_code(session, "summary")
            )

        sys_prompt: str = dto.prompt
        retry_prompt: str = dto.retry_prompt or ""

        for i in range(3):
            temperature: float = 0.1 * i
            if i == 2:
                sys_prompt = retry_prompt

            user_input: str = ""
            for msg in msg_list:
                if msg.msg_type in ["user_message", "assistant_message"]:
                    user_input += msg.date.isoformat(sep=" ", timespec="seconds") + "\n"
                    user_input += msg.sent_by + "\n"
                    user_input += msg.content + "\n\n"

            messages: list[dict] = []
            messages.append({"role": "system", "content": sys_prompt})
            user_msg: MessageDTO = MessageDTO.get_user_msg(user_input, True)
            messages.append(user_msg.to_msg())

            content: str = ""

            (
                _,
                content,
            ) = await self.getResponse(
                agent=self,
                response=await self.send(
                    messages=messages,
                    user_msg=user_msg,
                    is_think_mode=True,
                    temperature=temperature,
                ),
            )

            if content:
                content = re.sub(r"```json|```", "", content)

                records = self._load_records(content)
                if not records:
                    continue
                
                # 收集所有 records 的數據
                records_data: List[tuple] = []
                for record in records:
                    embedding_text = str(record.get("embedding_text", "")).strip()
                    importance: int = self._parse_importance(
                        record.get("importance_score")
                    )
                    
                    vector: Optional[List[float]] = None
                    if embedding_text:
                        vector = await self._embed_text(embedding_text)

                    records_data.append((record, vector, importance))

                # 同一個 JSON 的所有 records 在同一個 transaction 中 commit
                ConnPool.start_db_async_task(
                    self._save_long_term_memories_batch(
                        records_data,
                        [msg.id for msg in msg_list],
                    )
                )
                break

    def _load_records(self, content: str) -> Optional[List[Dict[str, Any]]]:
        """從 JSON 內容中載入 records 陣列"""
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                # 如果有 records 欄位，返回 records 陣列
                records = data.get("records")
                if isinstance(records, list):
                    return records
                # 如果沒有 records，但整個 object 就是一個 record，返回單元素陣列
                if "embedding_text" in data:
                    return [data]
            elif isinstance(data, list):
                return data
            print("Summary payload does not contain valid records.")
        except json.JSONDecodeError as exc:
            print(f"Failed to parse summary JSON: {exc}")
        return None

    def _parse_importance(self, value: Any) -> int:
        default_importance = 5
        try:
            importance = int(value)
            return max(1, min(10, importance))  # 限制在 1-10 範圍
        except (TypeError, ValueError):
            return default_importance

    async def _embed_text(self, text: str) -> Optional[List[float]]:
        """使用 EmbeddingAgent 將文本轉換為向量"""
        try:
            embedding = await self.embedding_agent.embed_query(text)
            return embedding
        except Exception as exc:
            print(f"Embedding request failed: {exc}")
            return None

    async def _save_long_term_memories_batch(
        self,
        records_data: List[tuple[Dict[str, Any], Optional[List[float]], int]],
        msg_ids: list[int]
    ) -> None:
        """批量保存同一個 JSON 的所有 LongTermMemory，確保同一時間 commit，並標記相關 message 為已摘要"""
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            # 保存所有 LongTermMemory records
            for record, vector, importance in records_data:
                await LongTermMemoryDAO().create(
                    session,
                    agent_id=self.db_id,
                    content=record,
                    vector_content=vector,
                    importance=importance,
                )
            # 在同一 transaction 中標記 message 為已摘要
            if msg_ids:
                await MessageDAO().mark_as_summarized(session, msg_ids)
            await session.commit()

    async def init_agent(self):
        """
        初始化 Agent 的記憶區塊 (memory_block)
        
        步驟:
        1. Check agent table is_inited = false
        2. 到 prompt table 用 prompt_type "init_agent" 拎 prompt
        3. 用 prompt 作為 system prompt, agent 的 sys_prompt 作為 user input, call LLM Think mode
        4. JSON response 解析並保存到 memory_block table
        5. agent 的 is_inited set 做 true
        6. 全部 db change 用同一個 transaction commit
        
        返回:
            bool: 成功返回 True，失敗或已初始化返回 False
        """
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            prompt_dao = PromptDAO()
            prompt_model = await prompt_dao.get_by_code(session, "init_agent")
            
            if not prompt_model:
                print("⚠️ init_agent prompt 不存在")
                await session.rollback()
                return False
            
            sys_prompt: str = prompt_model.prompt
            user_input: str = self.sys_prompt[0] if isinstance(self.sys_prompt, tuple) else self.sys_prompt
            
            # 3. 用 prompt 作為 system prompt, agent 的 sys_prompt 作為 user input, call LLM Think mode
            messages: list[dict] = []
            messages.append({"role": "system", "content": sys_prompt})
            messages.append({"role": "user", "content": user_input})
            
            user_msg = MessageDTO.get_user_msg(user_input, True)
            
            content : str = ""
            for i in range(3):
                temperature: float = 0.1 * i
                response = await self.send(messages, user_msg, True, temperature)
            
                _, content = await Agent.getResponse(
                    agent=self,
                    response=response,
                )
                
                if content:
                    break
            
            if not content:
                print("⚠️ LLM 返回空內容")
                await session.rollback()
                return False
            
            # 解析 JSON
            try:
                content = re.sub(r"```json|```", "", content)
                data = json.loads(content)
            except json.JSONDecodeError as exc:
                print(f"Failed to parse init_agent JSON: {exc}")
                await session.rollback()
                return False
            
            # 4. JSON 的每一個 key (soul, identity, user_profile) 作為 memory_block 的 block_type
            # { "content": "...", "importance": 10 } json save 入 content
            # json 入面的 "content" value 變成 vector save 入 vector_content
            memory_block_dao = MemoryBlockDAO()
            embedding_agent = EmbeddingAgent()
            
            for block_type in ["soul", "identity", "user_profile"]:
                if block_type not in data:
                    continue
                
                block_data = data[block_type]
                if not isinstance(block_data, dict):
                    continue
                
                # content 字段用於 vector embedding
                content_text = block_data.get("content", "")
                if not content_text:
                    continue
                
                # 計算 vector
                vector: Optional[List[float]] = None
                try:
                    vector = await embedding_agent.embed_query(content_text)
                except Exception as exc:
                    print(f"Embedding request failed for {block_type}: {exc}")
                
                # 保存到 memory_block
                await memory_block_dao.create(
                    session,
                    agent_id=self.db_id,
                    block_type=block_type,
                    content=block_data,  # 整個 { "content": "...", "importance": 10 } json
                    vector_content=vector,
                    is_active=True,
                )
            
            # 5. agent 的 is_inited set 做 true
            await AgentDAO().set_inited(session, self.db_id)
            
            # 6. 全部 db change 用同一個 transaction commit
            await session.commit()
