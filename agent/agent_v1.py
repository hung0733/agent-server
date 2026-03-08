import asyncio
from typing import AsyncGenerator, Dict, Iterable
import uuid

from sqlalchemy.future import select
from db.models import AgentModel, MessageModel
from dto.message import MessageDTO
from global_var import GlobalVar
from llm.brain_agent import BrainAgent

class AgentV1:
    def __init__(self, db_id : int, agent_id: str, name: str, sys_prompt: str, brain_slot_id: int, sum_slot_id: int):
        self.db_id = db_id
        self.agent_id = agent_id
        self.name = name
        self.sys_prompt = sys_prompt
        self.brain_slot_id = brain_slot_id
        self.sum_slot_id = sum_slot_id
        self.brain = BrainAgent(self.brain_slot_id, False)

    @classmethod
    async def get_agent(cls, agent_id: str):
        """
        喺 DB 攞資料並初始化 Agent
        """
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            # 喺 DB 搵對應嘅 agent_id
            query = select(AgentModel).where(AgentModel.agent_id == agent_id)
            result = await session.execute(query)
            db_agent : AgentModel = result.scalars().first()

            if not db_agent:
                print(f"⚠️ Agent {agent_id} 唔存在喺資料庫。")
                return None

            # 攞到資料，返傳實例
            return cls(
                db_id = db_agent.id,  # type: ignore
                agent_id= db_agent.agent_id, # type: ignore
                name= db_agent.name, # type: ignore
                sys_prompt= db_agent.sys_prompt, # type: ignore
                brain_slot_id= db_agent.brain_slot_id, # type: ignore
                sum_slot_id= db_agent.sum_slot_id # type: ignore
            )
    
    async def chat(self, user_input: str, is_think_mode : bool = False):
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            query = select(MessageModel).where(MessageModel.agent_id == self.db_id).order_by(MessageModel.create_date.asc())
            result = await session.execute(query)
            historys : list[MessageDTO] = [MessageDTO.get(m) for m in (result.scalars().all() or [])]
            
            messages : list[Dict[str, str]] = []
            
            if self.sys_prompt:
                messages.append({"role": "system", "content": f"{self.sys_prompt}"})
                
            for m in historys:
                messages.append(m.to_msg())
                
            pend_save : list[MessageDTO] = []
            
            user_msg : MessageDTO = MessageDTO.get_user_msg(user_input, is_think_mode)
            pend_save.append(user_msg)
            messages.append(user_msg.to_msg())
            
            print(f"🤖 Agent [{self.name}] 思考中...")
            
            raw_response = self.brain.send(messages, is_think_mode)
            
            # 4. 定義內部 Async Generator 嚟處理唔同型別同埋背景儲存
            async def wrapped_generator() -> AsyncGenerator[str, None]:
                full_content = ""
                full_reasoning = ""
                is_currently_reasoning = False
                
                if isinstance(raw_response, Iterable):
                    for chunk in raw_response:
                        if not isinstance(chunk, str):
                            continue
                            
                        # 標籤解析邏輯
                        if chunk == "<think>":
                            is_currently_reasoning = True
                            yield "---------- 思考中 ----------"
                            continue # 唔使 yield 俾 User
                        elif chunk == "</think>":
                            is_currently_reasoning = False
                            yield "---------------------------"
                            continue # 唔使 yield 俾 User
                        
                        if is_currently_reasoning:
                            full_reasoning += chunk
                            yield chunk
                        else:
                            full_content += chunk
                            yield chunk
                
                if full_reasoning:
                    pend_save.append(MessageDTO.get_reasoning_msg(full_reasoning, is_think_mode))
                pend_save.append(MessageDTO.get_assistant_msg(full_content, is_think_mode))
                
                # 開啟背景任務儲存，唔會塞住個 return
                asyncio.create_task(self._save_messages_to_db(pend_save))
            
            return wrapped_generator()
        
    async def _save_messages_to_db(self, messages: list[MessageDTO]):
        try:
            async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
                step_id = "step-" + str(uuid.uuid4()) # 呢一轉對話嘅 ID
                
                for msg_dto in messages:
                    new_msg = MessageModel(
                        agent_id=self.db_id,
                        step_id=step_id,
                        msg_id="msg-" + str(uuid.uuid4()),
                        msg_type=msg_dto.msg_type,
                        content=msg_dto.content,
                        is_think_mode=msg_dto.is_think_mode,
                        sent_by=msg_dto.sent_by
                    )
                    session.add(new_msg)
                
                await session.commit()
                print(f"💾 歷史訊息已成功存入資料庫 (Agent: {self.name})")
        except Exception as e:
            print(f"❌ 儲存訊息失敗: {e}")