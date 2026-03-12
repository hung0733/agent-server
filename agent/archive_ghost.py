import json
import os
import re
from typing import Any, Dict, List, Optional

from agent.agent import Agent
from db.agent_dao import AgentDAO
from db.conn_pool import ConnPool
from db.long_term_memory_dao import LongTermMemoryDAO
from db.message_dao import MessageDAO
from db.prompt_dao import PromptDAO
from db.soul_memory_dao import SoulMemoryDAO
from dto.agent import AgentDTO
from dto.message import MessageDTO
from dto.prompt import PromptDTO
from dto.session import SessionDTO
from dto.soul_memory import SoulMemoryDTO
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
                is_inited=agent.is_inited,
            )
        return None
    
    async def init_agent(self):
        if self.is_inited:
            return
        
        dto: PromptDTO
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            dto = PromptDTO.from_model(
                await PromptDAO().get_by_code(session, "init_agent")
            )
            
        user_input : str = dto.prompt + self.sys_prompt
        
        messages: list[dict] = []
        user_msg: MessageDTO = MessageDTO.get_user_msg(user_input, True)
        messages.append(user_msg.to_msg())
        
        data: Optional[List[Dict[str, Any]]] = None
        for i in range(3):
            temperature: float = 0.1 * i
            
            print("Analyse Genesis Message\n")
            (
                _,
                content,
            ) = await self.getResponse(
                agent=self,
                response=await self.send(
                    messages=messages,
                    pend_save=[user_msg],
                    is_think_mode=True,
                    temperature=temperature,
                ),
            )

            if content:
                content = re.sub(r"```json|```", "", content)
                data = self._load_memory_records(content)
                if not data:
                    continue
                break
        
        if data:
            print("Collect JSON Records\n")
            mem_list : list[SoulMemoryDTO] = []
            if "law_updates" in data:
                for item in data["law_updates"]:
                    mem_list.append(SoulMemoryDTO.from_json(
                        category="law",
                        data=item,
                        embedding_vector=await self._embed_text(item.get("content", ""))
                    ))
        
            if "soul_updates" in data:
                for item in data["soul_updates"]:
                    mem_list.append(SoulMemoryDTO.from_json(
                        category="soul",
                        data=item,
                        embedding_vector=await self._embed_text(item.get("content", ""))
                    ))
        
            if "identity_updates" in data:
                for item in data["identity_updates"]:
                    mem_list.append(SoulMemoryDTO.from_json(
                        category="identity",
                        data=item,
                        embedding_vector=await self._embed_text(item.get("content", ""))
                    ))
        
            if "user_profile_updates" in data:
                for item in data["user_profile_updates"]:
                    mem_list.append(SoulMemoryDTO.from_json(
                        category="user_profile",
                        data=item,
                        embedding_vector=await self._embed_text(item.get("content", ""))
                    ))
                    
            if mem_list:
                print("Save init memory to Database")
                async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
                    for mem in mem_list:
                        await SoulMemoryDAO().create(
                            session=session,
                            category=mem.category,
                            mem_key=mem.mem_key,
                            content=mem.content,
                            embedding=mem.embedding,
                            confidence=mem.confidence,
                            status=mem.status,
                            metadata=mem.meta_data
                        )
                    await AgentDAO().set_inited(session, self.db_id)
                    await session.commit()
                    print("Success to init memory")
        

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
                    user_input += msg.sent_by + ":\n"
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
                    pend_save=[user_msg],
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
            
    async def distillation(self, msg_list: list[MessageDTO]):
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
                    user_input += msg.sent_by + ":\n"
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
                    pend_save=[user_msg],
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

    def _load_memory_records(self, content: str) -> Optional[List[Dict[str, Any]]]:
        """從 JSON 內容中載入 records 陣列"""
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                if "law_updates" in data or "soul_updates" in data or "identity_updates" in data or "user_profile_updates" in data:
                    return data
            elif isinstance(data, list):
                return data
            print("memory payload does not contain valid records.")
        except json.JSONDecodeError as exc:
            print(f"Failed to parse summary JSON: {exc}")
        return None

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
            print("payload does not contain valid records.")
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
        msg_ids: list[int],
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
