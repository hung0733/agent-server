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

    def send(self, sys_prompt : str, input : str, is_think_mode : bool = False):
        messages: list[Dict[str, str]] = []
        
        if sys_prompt:
            messages.append({"role": "system", "content": sys_prompt})
        messages.append({"role": "user", "content": input})
        
        return self._send(messages, is_think_mode)
        
    def _send(self, messages: list[Dict[str, str]], is_think_mode : bool = False):
        return self.client.send(messages, is_think_mode)
