from typing import Optional
from openai.types.chat import ChatCompletion
import os
from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession

load_dotenv()

from llm.llm_agent import LlmAgent
from db.prompt_dao import PromptDAO


class RoutingAgent:
    """
    簡單的 Routing Agent
    - 使用 ROUTING_LLM_END_POINT
    - 純 send 收，不保存 Message 到 DB
    """
    
    def __init__(self):
        self.endpoint = os.getenv("ROUTING_LLM_END_POINT", "")
        self.api_key = os.getenv("ROUTING_LLM_API_KEY", "")
        self.model = os.getenv("ROUTING_LLM_MODEL", "")
        
        if not self.endpoint:
            raise ValueError("ROUTING_LLM_END_POINT 未設定")
        
        # Routing Agent 永遠不使用串流
        self.client = LlmAgent(
            endpoint=self.endpoint,
            api_key=self.api_key,
            model=self.model,
            stream=False
        )
    
    async def send(
        self,
        content: str,
        sys_prompt: Optional[str] = None,
    ) -> str:
        """
        發送內容到 ROUTING_LLM 並返回回應
        
        Args:
            content: 用戶輸入的內容
            sys_prompt: 可選的系統提示詞
            
        Returns:
            LLM 的文字回應
        """
        messages: list[dict[str, str]] = []
        
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        
        messages.append({"role": "user", "content": content})
        
        # Routing Agent 永遠不使用 think mode，temperature 固定為 0.1
        response = await self.client.send(messages, is_think_mode=False, temperature=0.1)
        
        # 提取回應內容（確保是 ChatCompletion）
        if isinstance(response, ChatCompletion) and response.choices:
            msg_obj = response.choices[0].message
            msg_data = (
                msg_obj.model_dump() if hasattr(msg_obj, "model_dump") else {}
            )
            return (
                msg_data.get("content") or getattr(msg_obj, "content", "") or ""
            ).strip()
        
        return ""
    
    async def close(self):
        """關閉客戶端連接"""
        await self.client.close()
    
    async def analyse_search_keyword(
        self,
        session: AsyncSession,
        user_input: str,
    ) -> str:
        """
        分析搜索關鍵詞
        
        Args:
            session: 資料庫 session
            user_input: 用戶輸入的內容
            
        Returns:
            LLM 分析後的關鍵詞內容
        """
        prompt_dao = PromptDAO()
        prompt_model = await prompt_dao.get_by_code(session, "search_keyword")
        
        if not prompt_model:
            raise ValueError("未找到 search_keyword 類型的 prompt")
        
        sys_prompt = str(prompt_model.prompt)
        
        return await self.send(user_input, sys_prompt)
