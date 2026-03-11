import asyncio
import os
from typing import Dict
from client.openai_client import OpenAIClient

import os
from llm.llm_agent import LlmAgent  # 匯入類型定義


class SummaryAgent(LlmAgent):
    def __init__(self, stream: bool = False):
        endpoint = os.getenv("SUMMARY_LLM_END_POINT", "http://localhost:8080/v1")
        api_key = os.getenv("SUMMARY_LLM_API_KEY", "no-key")
        model = os.getenv("SUMMARY_LLM_MODEL", "mamba")
        
        super().__init__(endpoint, api_key, model, stream)
