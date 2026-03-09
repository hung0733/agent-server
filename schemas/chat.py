from pydantic import BaseModel, Field
from typing import Optional, List, Literal


class ChatMessage(BaseModel):
    """OpenAI 標準的訊息格式"""
    role: Literal["system", "user", "assistant"] = Field(..., description="訊息角色")
    content: str = Field(..., description="訊息內容")
    reasoning_content: Optional[str] = Field(None, description="模型思考過程（可選）")


class ChatCompletionRequest(BaseModel):
    """OpenAI 標準的聊天完成請求"""
    model: str = Field(..., description="使用的模型名稱")
    messages: List[ChatMessage] = Field(..., description="對話歷史訊息列表")
    stream: bool = Field(False, description="是否使用 SSE 串流模式")
    allow_think: Optional[bool] = Field(False, description="是否允許模型進行思考/推理，預設為 False")


class ChoiceDelta(BaseModel):
    """串流回應的 Delta 格式"""
    role: Optional[Literal["system", "user", "assistant"]] = Field(None, description="角色（僅在第一個 chunk 出現）")
    content: Optional[str] = Field(None, description="內容片段")
    reasoning_content: Optional[str] = Field(None, description="思考過程片段（可選）")


class Usage(BaseModel):
    """Token 使用統計"""
    prompt_tokens: int = Field(..., description="提示詞使用的 token 數量")
    completion_tokens: int = Field(..., description="完成回應使用的 token 數量")
    total_tokens: int = Field(..., description="總 token 數量")


class Choice(BaseModel):
    """聊天完成選擇"""
    index: int = Field(0, description="選擇索引")
    delta: ChoiceDelta = Field(..., description="Delta 內容（串流模式）或最終結果（非串流模式）")
    finish_reason: Optional[Literal["stop", "length"]] = Field(None, description="結束原因")


class ChatCompletionResponse(BaseModel):
    """OpenAI 標準的聊天完成回應"""
    id: str = Field(..., description="回應 ID")
    object: Literal["chat.completion", "chat.completion.chunk"] = Field(
        ..., 
        description="回應物件類型（chat.completion 用於非串流，chat.completion.chunk 用於串流）"
    )
    created: int = Field(..., description="建立時間戳記（秒）")
    model: str = Field(..., description="使用的模型名稱")
    choices: List[Choice] = Field(..., description="回應選擇列表")
    usage: Optional[Usage] = Field(None, description="Token 使用統計（僅非串流模式）")


class ModelItem(BaseModel):
    """模型清單項目"""
    id: str = Field(..., description="模型 ID")
    object: Literal["model"] = Field("model", description="物件類型固定為 model")
    created: int = Field(0, description="建立時間戳記（秒）")
    owned_by: Literal["agent-server"] = Field("agent-server", description="擁有者")


class ListModelsResponse(BaseModel):
    """模型清單回應"""
    object: Literal["list"] = Field("list", description="物件類型固定為 list")
    data: List[ModelItem] = Field(..., description="模型列表")