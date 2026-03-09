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
        slot_id: int = 0
    ):
        self.endpoint = endpoint.rstrip('/')
        self.api_key = api_key
        self.model_name = model_name
        self.stream = stream
        self.slot_id = slot_id
        
        # 初始化 OpenAI 客戶端
        self.client = OpenAI(
            base_url=self.endpoint,
            api_key=self.api_key
        )
        
    def send(self, messages: list[Dict[str, str]], is_think_mode : bool = False) -> Union[str, Generator[str, None, None]]:
        
        extra_body = {
            "top_k": 20,
            "repetition_penalty": 1.0 if is_think_mode else 1.1,
            "chat_template_kwargs": {"enable_thinking": is_think_mode},
            "slot_id": self.slot_id
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
                msg = response.choices[0].message
                reasoning = getattr(msg, 'reasoning_content', None)
                content = msg.content or ""
                if reasoning:
                    return f"<think>{reasoning}</think>{content}"
                return content
            else:
                # 定義 generator 傳返出去
                def gen():
                    has_started_thinking = False
                    for chunk in response:
                        if not chunk.choices:
                            continue
                        
                        delta = chunk.choices[0].delta
                        
                        # 處理 Reasoning 
                        reasoning = getattr(delta, 'reasoning_content', None)
                        if reasoning:
                            if not has_started_thinking:
                                yield "<think>"
                                has_started_thinking = True
                            yield reasoning
                            
                        # 處理 Content
                        if delta.content:
                            # 如果 content 開始咗但仲未收返粒 think 掣，就補返個掣俾佢
                            if has_started_thinking:
                                yield "</think>"
                                has_started_thinking = False
                            yield delta.content
                            
                    # 完結時檢查
                    if has_started_thinking:
                        yield "</think>"
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