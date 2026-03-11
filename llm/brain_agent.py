import os
from llm.llm_agent import LlmAgent  # 匯入類型定義


class BrainAgent(LlmAgent):
    def __init__(self, stream: bool = True):
        endpoint = os.getenv("BRAIN_LLM_END_POINT", "http://localhost:8080/v1")
        api_key = os.getenv("BRAIN_LLM_API_KEY", "no-key")
        model = os.getenv("BRAIN_LLM_MODEL", "mamba")
        
        super().__init__(endpoint, api_key, model, stream)