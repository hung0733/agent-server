import os
from client.openai_client import OpenAIClient

class BrainAgent:
    def __init__(self):
        # 修正：用 os.getenv，並加上預設值或 Error Check
        endpoint = os.getenv("BRAIN_LLM_END_POINT", "http://localhost:8080/v1")
        api_key = os.getenv("BRAIN_LLM_API_KEY", "no-key")
        model = os.getenv("BRAIN_LLM_MODEL", "mamba")
        
        
        self.client = OpenAIClient(
            endpoint=endpoint,
            api_key=api_key,
            model_name=model,
            stream=True  # 預設行串流
        )

    def think(self, prompt: str):
        """
        處理邏輯並回傳串流
        """
        messages = [
            {"role": "system", "content": "你係 BrainAgent，負責深度思考同解答。"},
            {"role": "user", "content": prompt}
        ]
        
        # 直接 call client.send，佢會 return 個 generator
        gen = self.client.send(messages)
        
        # 繼續 yield 出去俾最外面嗰層（例如 UI 或 API）
        if hasattr(gen, '__iter__'): # 檢查係咪可迭代 (Generator)
            for chunk in gen:
                yield chunk
        else:
            yield gen # 如果係 Error String 就直接 yield 嗰個 String
