from client.openai_client import OpenAIClient
from typing import Dict, AsyncGenerator, Union
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from client.openai_client import OpenAIClient


class LlmAgent:
    def __init__(self, endpoint: str, api_key: str, model: str, stream: bool = True):
        self.stream = stream
        self.client = OpenAIClient(
            endpoint=endpoint, api_key=api_key, model_name=model, stream=stream
        )

    async def send(
        self,
        messages: list[Dict[str, str]],
        is_think_mode: bool = False,
        temperature: float = -1,
    ) -> Union[ChatCompletion, AsyncGenerator[ChatCompletionChunk, None]]:

        return await self.client.send(messages, is_think_mode, temperature)

    async def close(self):
        """當 Agent 銷毀時，確保連線有被關閉"""
        await self.client.dispose()
