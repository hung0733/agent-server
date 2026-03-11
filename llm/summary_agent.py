import asyncio
import os
from typing import Dict
from client.openai_client import OpenAIClient

class SummaryAgent:
    def __init__(self):
        endpoint = os.getenv("SUMMARY_LLM_END_POINT", "http://localhost:8080/v1")
        api_key = os.getenv("SUMMARY_LLM_API_KEY", "no-key")
        model = os.getenv("SUMMARY_LLM_MODEL", "mamba")
        
        self.client = OpenAIClient(
            endpoint=endpoint,
            api_key=api_key,
            model_name=model,
            stream=True
        )

    async def send(self, sys_prompt : str, input : str, is_think_mode : bool = False):
        messages: list[Dict[str, str]] = []
        
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.append({"role": "user", "content": input})
        
        gen = self._send(messages, is_think_mode)
    
        if hasattr(gen, '__iter__') and not isinstance(gen, str):
            # 將 sync generator 轉換為 async generator（流式模式）
            for chunk in gen:
                await asyncio.sleep(0)  # 讓出控制權，使這個函數真正成為 async generator
                yield chunk
        else:
            # 非流式模式：gen 是完整的 response 對象
            # 從 response 中提取 content 並 yield
            await asyncio.sleep(0)
            if hasattr(gen, 'choices') and gen.choices:
                content = gen.choices[0].message.content if hasattr(gen.choices[0], 'message') else gen.choices[0].delta.content
                yield content
            else:
                yield str(gen)
        
    def _send(self, messages: list[Dict[str, str]], is_think_mode : bool = False):
        return self.client.send(messages, is_think_mode)
