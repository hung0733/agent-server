import os
from typing import Dict
from client.openai_client import OpenAIClient

class BrainAgent:
    def __init__(self, slot_id : int = 0, enable_think : bool = False):
        # 修正：用 os.getenv，並加上預設值或 Error Check
        endpoint = os.getenv("BRAIN_LLM_END_POINT", "http://localhost:8080/v1")
        api_key = os.getenv("BRAIN_LLM_API_KEY", "no-key")
        model = os.getenv("BRAIN_LLM_MODEL", "mamba")
        
        
        self.client = OpenAIClient(
            endpoint=endpoint,
            api_key=api_key,
            model_name=model,
            stream=True,
            slot_id=slot_id
        )

    def send(self, messages: list[Dict[str, str]], is_think_mode : bool = False):
        gen = self.client.send(messages, is_think_mode)
        
        # 繼續 yield 出去俾最外面嗰層（例如 UI 或 API）
        if hasattr(gen, '__iter__'):
            for chunk in gen:
                yield chunk
        else:
            yield gen # 如果係 Error String 就直接 yield 嗰個 String
