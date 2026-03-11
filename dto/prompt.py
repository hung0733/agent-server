from datetime import datetime
from typing import TYPE_CHECKING, Any


class PromptDTO:
    """Prompt 數據傳輸對象"""
    
    id: int | None
    code: str
    prompt_type: str
    prompt: str
    retry_prompt: str | None
    
    def __init__(
        self,
        id: int | None = None,
        code: str | None = None,
        prompt_type: str | None = None,
        prompt: str | None = None,
        retry_prompt: str | None = None
    ) -> None:
        self.id = id
        self.code = code or ""
        self.prompt_type = prompt_type or ""
        self.prompt = prompt or ""
        self.retry_prompt = retry_prompt
    
    @classmethod
    def from_model(cls, model: Any) -> 'PromptDTO':
        """從 Model 轉換為 DTO"""
        return cls(
            id=model.id,
            code=model.code,
            prompt_type=model.prompt_type,
            prompt=model.prompt,
            retry_prompt=model.retry_prompt
        )