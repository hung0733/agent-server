import os
from typing import Dict, Tuple
from client.openai_client import OpenAIClient


class BrainAgent:
    def __init__(self, stream: bool = True):
        endpoint = os.getenv("BRAIN_LLM_END_POINT", "http://localhost:8080/v1")
        api_key = os.getenv("BRAIN_LLM_API_KEY", "no-key")
        model = os.getenv("BRAIN_LLM_MODEL", "mamba")
        
        self.stream = stream

        # 初始化串流客戶端（用於 chat()）
        self.stream_client = OpenAIClient(
            endpoint=endpoint,
            api_key=api_key,
            model_name=model,
            stream=stream
        )

    async def send(self, messages: list[Dict[str, str]], is_think_mode: bool = False):
        import asyncio

        if self.stream:
            gen = self.stream_client.send(messages, is_think_mode)
            
            if hasattr(gen, '__iter__') and not isinstance(gen, str):
                # 將 sync generator 轉換為 async generator
                for chunk in gen:
                    await asyncio.sleep(0)  # 讓出控制權，使這個函數真正成為 async generator
                    yield chunk
            else:
                await asyncio.sleep(0)
                yield gen
        else:
            return self.stream_client.send(messages, is_think_mode)