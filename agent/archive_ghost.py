import json
import os
import re
from typing import Any, Dict, List, Optional

import httpx
from agent.agent import Agent
from db.conn_pool import ConnPool
from db.long_term_memory_dao import LongTermMemoryDAO
from db.prompt_dao import PromptDAO
from dto.agent import AgentDTO
from dto.message import MessageDTO
from dto.prompt import PromptDTO
from dto.session import SessionDTO
from global_var import GlobalVar
from llm.brain_agent import BrainAgent


class ArchiveGhost(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = BrainAgent(self.stream)
        self.embedding_endpoint = os.getenv(
            "EMBEDDING_END_POINT", "http://localhost:8605/"
        )
        self.embedding_api_key = os.getenv("EMBEDDING_API_KEY", "")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")

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

            messages: list[MessageDTO] = []
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

                summary_payload = self._load_summary_payload(content)
                if not summary_payload:
                    continue

                embedding_text = str(summary_payload.get("embedding_text", "")).strip()
                importance: int = self._parse_importance(
                    summary_payload.get("importance_score")
                )

                vector: Optional[List[float]] = None
                if embedding_text:
                    vector = await self._embed_text(embedding_text)

                ConnPool.start_db_async_task(
                    self._save_long_term_memory(
                        summary_payload,
                        vector,
                        importance,
                        [msg.id for msg in msg_list],
                    )
                )
                break

    def _load_summary_payload(self, content: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                return data
            print("Summary payload is not a JSON object.")
        except json.JSONDecodeError as exc:
            print(f"Failed to parse summary JSON: {exc}")
        return None

    def _parse_importance(self, value: Any) -> int:
        default_importance = 5
        try:
            importance = int(value)
            return max(1, importance)
        except (TypeError, ValueError):
            return default_importance

    async def _embed_text(self, text: str) -> Optional[List[float]]:
        url = self.embedding_endpoint.rstrip("/") + "/embeddings"
        headers = {"Content-Type": "application/json"}
        if self.embedding_api_key:
            headers["Authorization"] = f"Bearer {self.embedding_api_key}"

        payload = {"model": self.embedding_model, "input": text}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except Exception as exc:
            print(f"Embedding request failed: {exc}")
            return None

        data = body.get("data")
        if not data:
            print("Embedding response missing data field.")
            return None

        embedding = data[0].get("embedding")
        if isinstance(embedding, list):
            try:
                return [float(value) for value in embedding]
            except (TypeError, ValueError):
                print("Failed to convert embedding values to float.")
        else:
            print("Embedding response format invalid.")
        return None

    async def _save_long_term_memory(
        self,
        content: Dict[str, Any],
        vector: Optional[List[float]],
        importance: int,
        msg_ids : list[int]
    ) -> None:
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            await LongTermMemoryDAO().create(
                session,
                agent_id=self.db_id,
                content=content,
                vector_content=vector,
                importance=importance,
            )
            print(msg_ids)
            await session.commit()
