import os
from openai import OpenAI
from typing import Dict, Any, Optional, Generator, Union
from dotenv import load_dotenv

load_dotenv()

class OpenAIClient:
    def __init__(
        self, 
        endpoint: str, 
        api_key: str, 
        model_name: str,
        stream: bool = True,
        slot_id: int = 0,
        enable_think: bool = False
    ):
        self.endpoint = endpoint.rstrip('/')
        self.api_key = api_key
        self.model_name = model_name
        self.stream = stream
        self.slot_id = slot_id
        self.enable_think = enable_think
        
        # 初始化 OpenAI 客戶端
        self.client = OpenAI(
            base_url=self.endpoint,
            api_key=self.api_key
        )
        
    def send(self, messages: list[Dict[str, str]]) -> Union[str, Generator[str, None, None]]:
        # 根據是否開啟思考模式，動態調整內部參數
        extra_kwargs: Dict[str, Any] = {
            "temperature": 0.6 if self.enable_think else 0.7,
            "top_p": 0.95 if self.enable_think else 0.8,
            "presence_penalty": 0.0 if self.enable_think else 0.3,
            "extra_body": {
                "top_k": 20,
                "repetition_penalty": 1.0 if self.enable_think else 1.1,
                "chat_template_kwargs": {"enable_thinking": self.enable_think},
                "slot_id": self.slot_id
            }
        }
        
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                stream=self.stream,
                **extra_kwargs
            )
            
            if not self.stream:
                return response.choices[0].message.content
            else:
                # 定義 generator 傳返出去
                def gen():
                    for chunk in response:
                        # 檢查 chunk 同 content 是否存在
                        if chunk.choices and chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta.content
                return gen()
                
        except Exception as e:
            error_msg = f"連線出咗問題：{str(e)}"
            print(f"\n[OpenAIClient Error]: {error_msg}")
            return error_msg

    def dispose(self):
        """釋放資源"""
        if hasattr(self, 'client') and self.client is not None:
            self.client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.dispose()