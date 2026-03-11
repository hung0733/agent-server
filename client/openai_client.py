from openai import AsyncOpenAI  # 改用非同步
from typing import Dict, AsyncGenerator, Union
from openai.types.chat import ChatCompletion, ChatCompletionChunk  # 匯入類型定義


class OpenAIClient:
    def __init__(
        self, endpoint: str, api_key: str, model_name: str, stream: bool = True
    ):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.stream = stream

        # 初始化非同步客戶端
        self.client = AsyncOpenAI(base_url=self.endpoint, api_key=self.api_key)

    async def send(
        self,
        messages: list[Dict[str, str]],
        is_think_mode: bool = False,
        temperature: float = -1,
    ) -> Union[ChatCompletion, AsyncGenerator[ChatCompletionChunk, None]]:
        # 決定參數
        if temperature < 0:
            temperature = 0.6 if is_think_mode else 0.7

        extra_body = {
            "top_k": 20,
            "repetition_penalty": 1.0 if is_think_mode else 1.1,
            "chat_template_kwargs": {"enable_thinking": is_think_mode},
        }

        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,  # type: ignore
                stream=self.stream,
                temperature=temperature,
                top_p=0.95 if is_think_mode else 0.8,
                presence_penalty=0.0 if is_think_mode else 0.3,
                extra_body=extra_body,
            )

            if not self.stream:
                # 非串流模式：回傳完整 ChatCompletion 物件
                return response
            else:
                # 串流模式：定義 AsyncGenerator 回傳完整 Chunk 物件
                async def gen() -> AsyncGenerator[ChatCompletionChunk, None]:
                    async for chunk in response:
                        yield chunk  # 這裡直接輸出完整的 OpenAI Chunk 物件
                return gen()

        except Exception as e:
            # 建議這裡拋出異常，或者回傳特定的 Error 格式
            raise RuntimeError(f"OpenAI API 連線失敗: {str(e)}")

    async def dispose(self):
        """真正的釋放資源"""
        if self.client:
            await self.client.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.dispose()
