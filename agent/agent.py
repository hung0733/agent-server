from typing import AsyncGenerator, Dict, List, Optional, Tuple, Union
import json
import time
import uuid

from fastapi import HTTPException
import tiktoken

from db.agent_dao import AgentDAO
from db.conn_pool import ConnPool
from db.long_term_memory_dao import LongTermMemoryDAO
from db.memory_block_dao import MemoryBlockDAO
from db.message_dao import MessageDAO
from db.session_dao import SessionDAO
from dto.agent import AgentDTO
from dto.message import MessageDTO
from dto.session import SessionDTO
from global_var import GlobalVar
from llm.embedding_agent import EmbeddingAgent
from openai.types.chat import ChatCompletion, ChatCompletionChunk  # 匯入類型定義


class Agent:
    def __init__(
        self,
        db_id: int,
        agent_id: str,
        session_db_id: int,
        session_id: str,
        name: str,
        sys_prompt: str,
        stream: bool,
        is_inited:bool
    ):
        self.db_id = db_id
        self.agent_id = agent_id
        self.session_db_id = session_db_id
        self.session_id = session_id
        self.name = name
        self.sys_prompt = sys_prompt
        self.stream = stream
        self.is_inited = is_inited

    async def chat(
        self, user_input: str, is_think_mode: bool = False
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        message_dao = MessageDAO()
        memory_block_dao = MemoryBlockDAO()
        long_term_memory_dao = LongTermMemoryDAO()
        embedding_agent = EmbeddingAgent()

        # 1. 獲取歷史紀錄
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            historys = await message_dao.get_unsummarized_messages(session, self.session_db_id)

        # 2. 構建 messages
        messages: list[Dict[str, str]] = []
        
        # 決定 system prompt
        prompt_str: str = ""
        
        if self.is_inited:
            for block_type in ["soul", "identity", "user_profile"]:
                memory_blocks = await memory_block_dao.get_active_by_agent_id_and_type(
                    session, self.db_id, block_type
                )
                for block in memory_blocks:
                    # block.content 是 { "content": "...", "importance": N }，直接 json 輸出
                    content_text = json.dumps(block.content, ensure_ascii=False)
                    if content_text:
                        if block_type == "soul":
                            prompt_str += f"你的核心靈魂： {content_text}\n\n"
                        elif block_type == "identity":
                            prompt_str += f"你的身份設定 {content_text}\n\n"
                        elif block_type == "user_profile":
                            prompt_str += f"關於你的主人： {content_text}\n\n"

        # 如果沒有從 memory_block 獲取到 prompt，使用原本的 sys_prompt
        if not prompt_str and self.sys_prompt:
            prompt_str = (
                self.sys_prompt
                if isinstance(self.sys_prompt, str)
                else str(self.sys_prompt)
            )
        
        if prompt_str:
            messages.append({"role": "system", "content": prompt_str})

        for m in historys:
            messages.append(MessageDTO.from_model(m).to_msg())

        # RAG 功能：從 long term memory 檢索相關記憶
        # 1. 用 user_input 變成 vector
        embed_start = time.time()
        query_vector = await embedding_agent.embed_query(user_input)
        embed_time = time.time() - embed_start
        print(f"[Embedding] 生成 query vector 用咗 {embed_time:.3f} 秒")
        
        # 2. 用 Cosine Distance 搵出最接近的 10-15 條（相似度 > 0.45）
        similar_memories = await long_term_memory_dao.get_similar_memories(
            session, self.db_id, query_vector, top_k=15, similarity_threshold=0.45
        )
        
        # 初始化 pend_save（無論有無相似記憶都需要）
        pend_save: list[MessageDTO] = []
        
        # 3. 將呢 10 幾條記憶連同用戶問題，一齊 send 去 Reranking
        if similar_memories:
            documents = [json.dumps(mem.content, ensure_ascii=False) for mem in similar_memories]
            
            # 4. 攞 Reranker 分數最高嗰 3-5 條
            rerank_start = time.time()
            rerank_results = await embedding_agent.rerank(
                query=user_input,
                documents=documents,
                top_n=3
            )
            rerank_time = time.time() - rerank_start
            print(f"[Rerank] Reranking 用咗 {rerank_time:.3f} 秒")
            
            # 過濾：只保留 score > -7.0 的結果
            filtered_results = [(idx, score) for idx, score in rerank_results if score > -7.0]
            print(f"[Rerank] 過濾後剩餘 {len(filtered_results)} 條記憶 (score > -7.0)")
            
            # 5. 將 assistant_message 放入 user_msg 之前
            if filtered_results:
                # 組合最高分數的記憶作為 context
                context_parts = []
                for idx, score in filtered_results:
                    context_parts.append(f"[相關記憶] {documents[idx]} (相關性：{score:.2f})")
                
                context_text = "\n\n".join(context_parts)
                print(context_text)
                # 創建 assistant_message 的 MessageDTO
                memory_msg = MessageDTO.get_assistant_msg(
                    f"根據相關記憶，我找到以下資訊：\n\n{context_text}",
                    is_think_mode
                )
                messages.append(memory_msg.to_msg())
                pend_save.append(memory_msg)

        # 加入使用者當前輸入
        user_msg = MessageDTO.get_user_msg(user_input, is_think_mode)
        messages.append(user_msg.to_msg())
        pend_save.append(user_msg)

        return await self.send(messages, pend_save, is_think_mode)

    async def send(
        self,
        messages: list[Dict[str, str]],
        pend_save: list[MessageDTO],
        is_think_mode: bool,
        temperature: float = -1,
    ):
        return self.handleMsgResponse(
            self,
            is_think_mode,
            pend_save,
            await self.client.send(messages, is_think_mode, temperature),
        )

    @staticmethod
    async def get_db_agent(
        agent_id: str, session_id: str = "default"
    ) -> tuple[Optional[AgentDTO], Optional[SessionDTO]]:
        """
        喺 DB 攞資料並初始化 Agent (使用 DAO)
        """
        agent_dao = AgentDAO()
        session_dao = SessionDAO()

        agent_dto: Optional[AgentDTO] = None
        session_dto: Optional[SessionDTO] = None
        # 喺 DB 搵對應嘅 agent_id 同 session
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            db_agent = await agent_dao.get_by_agent_id(session, agent_id)

            if not db_agent:
                print(f"⚠️ Agent {agent_id} 唔存在喺資料庫。")
                return (agent_dto, session_dto)

            # 根據 session_id 獲取 Session (default 需要配合 agent_db_id，其他可以單獨查找)
            if session_id == "default":
                db_session = await session_dao.get_default_session(session, db_agent.id)
            else:
                db_session = await session_dao.get_by_session_id(session, session_id)

            if not db_session:
                print(f"⚠️ Session {session_id} 唔存在喺資料庫。")
                return (agent_dto, session_dto)

        # 檢查 agent 是否存在
        if not db_agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        # 檢查 session 是否存在
        if not db_session:
            raise HTTPException(
                status_code=404,
                detail=f"Session '{session_id}' not found for Agent '{agent_id}'",
            )

        return (AgentDTO.from_model(db_agent), SessionDTO.from_model(db_session))

    @staticmethod
    async def getResponse(
        agent: "Agent",
        response: Union[ChatCompletion, AsyncGenerator[ChatCompletionChunk, None]],
    ) -> Tuple[str, str]:
        full_reasoning: str = ""
        full_content: str = ""

        if agent.stream:
            # 4. 處理串流
            async for chunk in response:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    # 處理思考過程
                    reasoning = getattr(delta, "reasoning_content", None)
                    if reasoning:
                        full_reasoning += reasoning
                    # 處理回答內容
                    if delta.content:
                        full_content += delta.content
        else:
            # 2. 處理內部入 DB 用的數據
            try:
                # 1. 喺 yield 之前先將內容攞出嚟
                if hasattr(response, "choices") and response.choices:
                    msg_obj = response.choices[0].message
                    msg_data = (
                        msg_obj.model_dump() if hasattr(msg_obj, "model_dump") else {}
                    )

                    full_content = (
                        msg_data.get("content") or getattr(msg_obj, "content", "") or ""
                    )
                    full_reasoning = (
                        msg_data.get("reasoning_content")
                        or getattr(msg_obj, "reasoning_content", "")
                        or ""
                    )
            except Exception as e:
                print(f"ERROR [Agent.py] Extraction failed: {str(e)}")

        return (full_reasoning, full_content)

    @staticmethod
    async def handleMsgResponse(
        agent: "Agent",
        is_think_mode: bool,
        pend_save: list[MessageDTO],
        response: Union[ChatCompletion, AsyncGenerator[ChatCompletionChunk, None]],
    ) -> AsyncGenerator[ChatCompletionChunk, None]:
        full_reasoning: str = ""
        full_content: str = ""

        if agent.stream:
            # 4. 處理串流
            async for chunk in response:
                yield chunk

                if chunk.choices:
                    delta = chunk.choices[0].delta
                    # 處理思考過程
                    reasoning = getattr(delta, "reasoning_content", None)
                    if reasoning:
                        full_reasoning += reasoning
                    # 處理回答內容
                    if delta.content:
                        full_content += delta.content
            agent._prepare_save_messages_to_db(
                agent, pend_save, is_think_mode, full_content, full_reasoning
            )

        else:
            # 2. 處理內部入 DB 用的數據
            try:
                # 1. 喺 yield 之前先將內容攞出嚟
                if hasattr(response, "choices") and response.choices:
                    msg_obj = response.choices[0].message
                    msg_data = (
                        msg_obj.model_dump() if hasattr(msg_obj, "model_dump") else {}
                    )

                    full_content = (
                        msg_data.get("content") or getattr(msg_obj, "content", "") or ""
                    )
                    full_reasoning = (
                        msg_data.get("reasoning_content")
                        or getattr(msg_obj, "reasoning_content", "")
                        or ""
                    )

                print(
                    f"DEBUG [Agent.py]: Content Length = {len(full_content)}, Reasoning Length = {len(full_reasoning)}"
                )

            except Exception as e:
                print(f"ERROR [Agent.py] Extraction failed: {str(e)}")

            agent._prepare_save_messages_to_db(
                agent, pend_save, is_think_mode, full_content, full_reasoning
            )
            yield response

    @staticmethod
    def _prepare_save_messages_to_db(
        agent: "Agent",
        messages: list[MessageDTO],
        is_think_mode: bool,
        content: str,
        reasoning_content: str,
    ):

        if content:
            if reasoning_content:
                messages.append(
                    MessageDTO.get_reasoning_msg(reasoning_content, is_think_mode)
                )
            messages.append(MessageDTO.get_assistant_msg(content, is_think_mode))
            ConnPool.start_db_async_task(agent._save_messages_to_db(agent, messages))

    @staticmethod
    async def _save_messages_to_db(agent: "Agent", messages: list[MessageDTO]):
        message_dao = MessageDAO()

        try:
            step_id = "step-" + str(uuid.uuid4())  # 呢一轉對話嘅 ID

            async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
                for msg_dto in messages:
                    await message_dao.create(
                        session,
                        session_id=agent.session_db_id,
                        step_id=step_id,
                        msg_id="msg-" + str(uuid.uuid4()),
                        msg_type=msg_dto.msg_type,
                        content=msg_dto.content,
                        is_think_mode=msg_dto.is_think_mode,
                        sent_by=msg_dto.sent_by,
                        create_date=msg_dto.date,
                        token=Agent._count_tokens(msg_dto.content),
                    )

                await session.commit()

            print(f"💾 歷史訊息已成功存入資料庫 (Agent: {agent.name})")
        except Exception as e:
            print(f"❌ 儲存訊息失敗：{e}")

    @staticmethod
    def _count_tokens(text: str) -> int:
        """計吓段文字有幾多 Token"""
        try:
            return len(tiktoken.get_encoding("cl100k_base").encode(text))
        except Exception as e:
            print(f"⚠️ Token 計算失敗：{e}")
            return 0
