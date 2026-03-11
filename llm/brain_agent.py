import os
from typing import Dict, AsyncGenerator, Union
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from client.openai_client import OpenAIClient  # 匯入類型定義


class BrainAgent:
    def __init__(self, stream: bool = True):
        # 這些環境變數建議在外面傳進來，或者集中管理
        endpoint = os.getenv("BRAIN_LLM_END_POINT", "http://localhost:8080/v1")
        api_key = os.getenv("BRAIN_LLM_API_KEY", "no-key")
        model = os.getenv("BRAIN_LLM_MODEL", "mamba")

        self.stream = stream
        self.client = OpenAIClient(
            endpoint=endpoint, api_key=api_key, model_name=model, stream=stream
        )

    async def send(
        self, messages: list[Dict[str, str]], is_think_mode: bool = False
    ) -> Union[ChatCompletion, AsyncGenerator[ChatCompletionChunk, None]]:

        return await self.client.send(messages, is_think_mode)

    async def close(self):
        """當 Agent 銷毀時，確保連線有被關閉"""
        await self.client.dispose()