
from datetime import datetime
from email.generator import _MessageT
from typing import List, cast
import uuid
from agent.agent_v1 import AgentV1
from db.models import MessageModel
from global_var import GlobalVar
import tiktoken
import asyncio
import sys

class MessageDTO:
    msg_type : str
    is_think_mode : bool
    sent_by : str
    content : str
    date : datetime
    token : int
    
    def __init__(self, msg_type : str, is_think_mode : bool, sent_by : str, date : datetime, content : str, token : int) -> None:
        self.msg_type = msg_type
        self.is_think_mode = is_think_mode
        self.sent_by = sent_by
        self.date = date
        self.content = content
        self.token = token
    
    def to_msg(self):
        return {"role": self.sent_by, "content": self.content}
        
    @classmethod
    def get(cls, m : MessageModel):
        return cls(
            msg_type = m.msg_type,
            is_think_mode = m.is_think_mode,
            sent_by = m.sent_by,
            date = m.create_date,
            content = m.content,
            token = m.token
        )
        
    @classmethod
    def get_user_msg(cls, user_input: str, is_think_mode : bool, token: int = 0):
        return cls(
            msg_type = "user_message",
            is_think_mode = is_think_mode,
            sent_by = "user",
            date = datetime.now(),
            content = user_input,
            token = token
        )
    
        
    @classmethod
    def get_assistant_msg(cls, user_input: str, is_think_mode : bool, token: int = 0):
        return cls(
            msg_type = "assistant_message",
            is_think_mode = is_think_mode,
            sent_by = "assistant",
            date = datetime.now(),
            content = user_input,
            token = token
        )
        
    @classmethod
    def get_reasoning_msg(cls, user_input: str, is_think_mode : bool, token: int = 0):
        return cls(
            msg_type = "reasoning_message",
            is_think_mode = is_think_mode,
            sent_by = "assistant",
            date = datetime.now(),
            content = user_input,
            token = token
        )
        
    @staticmethod
    def count_tokens(text: str) -> int:
        """計吓段文字有幾多 Token"""
        try:
            return len(tiktoken.get_encoding("cl100k_base").encode(text))
        except Exception as e:
            print(f"⚠️ Token 計算失敗: {e}")
            return 0
        
    @staticmethod
    def save_message(agent : AgentV1, messages: list):
        try:
            async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
                step_id = "step-" + str(uuid.uuid4())  # 呢一轉對話嘅 ID

                for msg_dto in messages:
                    new_msg = MessageModel(
                        agent_id=agent.db_id,
                        session_id = agent.session_db_id,
                        step_id=step_id,
                        msg_id="msg-" + str(uuid.uuid4()),
                        msg_type=msg_dto.msg_type,
                        content=msg_dto.content,
                        is_think_mode=msg_dto.is_think_mode,
                        sent_by=msg_dto.sent_by,
                        create_date=msg_dto.date,
                        token = MessageDTO.count_tokens(msg_dto.content)
                    )
                    session.add(new_msg)

                await session.commit()
                print(f"💾 歷史訊息已成功存入資料庫 (Agent: {agent.name})")
        except Exception as e:
            print(f"❌ 儲存訊息失敗: {e}")