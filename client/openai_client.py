import os
from openai import OpenAI
from typing import Dict, Any, Optional, Generator, Union

class OpenAIClient:
    def __init__(
        self, 
        endpoint: str, 
        api_key: str, 
        model_name: str,
        stream: bool = True
    ):
        self.endpoint = endpoint.rstrip('/')
        self.api_key = api_key
        self.model_name = model_name
        self.stream = stream
        
        # 初始化 OpenAI 客戶端
        self.client = OpenAI(
            base_url=self.endpoint,
            api_key=self.api_key
        )
        
    def send(self, messages: list[Dict[str, str]], is_think_mode : bool = False) -> Union[str, Generator[str, None, None]]:
        
        extra_body = {
            "top_k": 20,
            "repetition_penalty": 1.0 if is_think_mode else 1.1,
            "chat_template_kwargs": {"enable_thinking": is_think_mode}
        }
        
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages, # type: ignore
                stream=self.stream,
                temperature=0.6 if is_think_mode else 0.7,
                top_p=0.95 if is_think_mode else 0.8,
                presence_penalty=0.0 if is_think_mode else 0.3,
                extra_body=extra_body 
            )
            
            if not self.stream:
                return response
            
            else:
                # 直接返回 generator，唔好修改原始 data
                def gen():
                    for chunk in response:
                        yield chunk
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