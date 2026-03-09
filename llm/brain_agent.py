import os
from typing import Dict, Tuple
from client.openai_client import OpenAIClient


class BrainAgent:
    def __init__(self):
        endpoint = os.getenv("BRAIN_LLM_END_POINT", "http://localhost:8080/v1")
        api_key = os.getenv("BRAIN_LLM_API_KEY", "no-key")
        model = os.getenv("BRAIN_LLM_MODEL", "mamba")

        # 初始化串流客戶端（用於 chat()）
        self.stream_client = OpenAIClient(
            endpoint=endpoint,
            api_key=api_key,
            model_name=model,
            stream=True
        )
        
        # 初始化非串流客戶端（用於 chat_non_stream()）
        self.non_stream_client = OpenAIClient(
            endpoint=endpoint,
            api_key=api_key,
            model_name=model,
            stream=False
        )

    async def send(self, messages: list[Dict[str, str]], is_think_mode: bool = False):
        """串流模式：發送訊息並產生回應片段（async generator）"""
        import asyncio
        
        gen = self.stream_client.send(messages, is_think_mode)

        if hasattr(gen, '__iter__') and not isinstance(gen, str):
            # 將 sync generator 轉換為 async generator
            for chunk in gen:
                await asyncio.sleep(0)  # 讓出控制權，使這個函數真正成為 async generator
                yield chunk
        else:
            await asyncio.sleep(0)
            yield gen

    def send_non_stream(self, messages: list[Dict[str, str]], is_think_mode: bool = False) -> Tuple[str, str]:
        """非串流模式：發送訊息並返回完整回應，同時提取 reasoning_content
        
        Args:
            messages: 對話歷史訊息列表
            is_think_mode: 是否允許模型進行思考
            
        Returns:
            Tuple[str, str]: (reasoning_content, content)
                - reasoning_content: 思考過程內容（從 response.choices[0].message.reasoning_content 提取）
                - content: 最終回應內容（response.choices[0].message.content）
        """
        # 直接返回原始 response，由 caller 處理
        return self.non_stream_client.send(messages, is_think_mode)