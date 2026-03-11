import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import AsyncGenerator, List

from db.conn_pool import get_db
from router.session_router import validate_session_id_format
from schemas.chat import (
    ChatMessage,
    ChatCompletionRequest,
    ChoiceDelta,
    Usage,
    Choice,
    Message,
    ChatCompletionResponse,
    ModelItem,
    ListModelsResponse,
)
from agent.agent_v1 import AgentV1


router = APIRouter()

# 可用的模型列表（可從配置或資料庫動態加載）
AVAILABLE_MODELS: List[ModelItem] = [
    ModelItem(id="mamba", object="model", created=0, owned_by="agent-server"),
    ModelItem(id="llama-3.1", object="model", created=0, owned_by="agent-server"),
    ModelItem(id="gpt-4o", object="model", created=0, owned_by="agent-server"),
]


@router.get("/agents/{agent_id}/v1/models")
async def list_agent_models(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> ListModelsResponse:
    """獲取 Agent 預設會話的可用模型列表"""
    # 驗證 Agent 是否存在
    try:
        await AgentV1.get_agent(agent_id=agent_id, session_id="default")
    except HTTPException as e:
        raise e
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    return ListModelsResponse(object="list", data=AVAILABLE_MODELS)


@router.get("/sessions/{session_id}/v1/models")
async def list_session_models(
    session_id: str,
    db: AsyncSession = Depends(get_db),
) -> ListModelsResponse:
    """獲取指定 Session 的可用模型列表"""
    # TODO: 驗證 Session 是否存在（需要根據實際業務邏輯實現）

    return ListModelsResponse(object="list", data=AVAILABLE_MODELS)


@router.post("/agents/{agent_id}/v1/chat/completions")
async def create_agent_chat_completion(
    request: ChatCompletionRequest,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Agent 預設會話的聊天完成端點（支援串流和非串流）"""
    # 獲取 Agent（使用預設 session="default"）
    try:
        agent = await AgentV1.get_agent(
            agent_id=agent_id, session_id="default", stream=request.stream
        )
    except HTTPException as e:
        raise e
    except Exception:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

    # 檢查 agent 是否為 None（get_agent 可能返回 None）
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    
    # 建議喺 agent_v1.py 加返
    print(f"DEBUG: Initializing AgentV1 with id: {agent_id}")

    if request.stream:
        return StreamingResponse(
            _stream_chat_completion(agent, request), media_type="text/event-stream"
        )
    else:
        return await _non_stream_chat_completion(agent, request)


@router.post("/sessions/{session_id}/v1/chat/completions")
async def create_session_chat_completion(
    request: ChatCompletionRequest,
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """指定 Session 的聊天完成端點（支援串流和非串流）"""
    # 從 session table 查找對應的 agent
    from db.models import SessionModel

    validate_session_id_format(session_id)

    try:
        # 查詢 session record
        result = await db.execute(
            select(SessionModel).where(SessionModel.session_id == session_id)
        )
        session_record = result.scalar_one_or_none()

        if not session_record:
            raise HTTPException(
                status_code=404, detail=f"Session '{session_id}' not found"
            )

        # 獲取對應的 agent_id
        agent_id = session_record.agent_id

        # 需要將 agent_id (int) 轉換為 agent.agent_id (string)
        from db.models import AgentModel

        result = await db.execute(select(AgentModel).where(AgentModel.id == agent_id))
        agent_model = result.scalar_one_or_none()

        if not agent_model:
            raise HTTPException(
                status_code=404, detail=f"Agent for session '{session_id}' not found"
            )

        # 獲取 AgentV1 實例
        agent = await AgentV1.get_agent(
            agent_id=agent_model.agent_id, session_id=session_id, stream=request.stream
        )
    except HTTPException as e:
        raise e
    except Exception:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    # 檢查 agent 是否為 None（get_agent 可能返回 None）
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    
    # 建議喺 agent_v1.py 加返
    print(f"DEBUG: Initializing AgentV1 with id: {agent_id}")

    if request.stream:
        return StreamingResponse(
            _stream_chat_completion(agent, request), media_type="text/event-stream"
        )
    else:
        return await _non_stream_chat_completion(agent, request)


async def _non_stream_chat_completion(
    agent: AgentV1,
    request: ChatCompletionRequest,
) -> ChatCompletionResponse:
    """非串流聊天完成處理"""
    # 根據 allow_think 參數決定是否啟用思考模式
    is_think_mode = request.allow_think if request.allow_think is not None else False

    # 獲取最後一條 user message 的內容
    last_user_msg = None
    for msg in reversed(request.messages):
        if msg.role == "user":
            last_user_msg = msg.content
            break

    if not last_user_msg:
        raise HTTPException(
            status_code=400, detail="No user message found in conversation"
        )

# 調用 Agent 的 chat 方法，依家佢返傳嘅係 AsyncGenerator
    response_gen = await agent.chat(last_user_msg, is_think_mode)

    content = ""
    reasoning_content = ""

    # 喺呢度消耗掉 AsyncGenerator 嚟攞返完整內容
    async for chunk in response_gen:
        # chunk 係 ChatCompletion 物件 (因為 handleMsgResponse 非串流時 yield 了完整物件)
        if hasattr(chunk, "choices") and chunk.choices:
            msg = chunk.choices[0].message
            content = msg.content or ""
            reasoning_content = getattr(msg, "reasoning_content", None) or ""
            # 非串流模式下，通常只有一個 chunk (即完整 response)
            break

    # 計算 token 使用量（簡單估算）
    prompt_tokens = sum(len(msg.content) for msg in request.messages) // 4
    completion_tokens = len(content) // 4

    if reasoning_content:
        completion_tokens += len(reasoning_content) // 4

    return ChatCompletionResponse(
        id="chatcmpl-" + str(uuid.uuid4()),
        object="chat.completion",
        created=0,
        model=request.model,
        choices=[
            Choice(
                index=0,
                message=Message(
                    role="assistant",
                    reasoning_content=reasoning_content,
                    content=content,
                ),
                finish_reason="stop",
            )
        ],
        usage=Usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


async def _stream_chat_completion(
    agent: AgentV1,
    request: ChatCompletionRequest,
) -> AsyncGenerator[str, None]:
    """串流聊天完成處理（SSE 格式）"""
    # 根據 allow_think 參數決定是否啟用思考模式
    is_think_mode = request.allow_think if request.allow_think is not None else False

    # 獲取最後一條 user message 的內容
    last_user_msg = None
    for msg in reversed(request.messages):
        if msg.role == "user":
            last_user_msg = msg.content
            break

    if not last_user_msg:
        error_response = ChatCompletionResponse(
            id="chatcmpl-" + str(uuid.uuid4()),
            object="chat.completion.chunk",
            created=0,
            model=request.model,
            choices=[Choice(index=0, delta=ChoiceDelta(), finish_reason="stop")],
            usage=None,
        )
        yield "data: " + error_response.model_dump_json() + "\n\n"
        yield "data: [DONE]\n\n"
        return

    # 調用 Agent 的串流方法，返回 AsyncGenerator（需要 await）
    response_gen = await agent.chat(last_user_msg, is_think_mode)

    # 發送第一個 chunk（包含 role）
    first_chunk = ChoiceDelta(role="assistant", content=None)
    first_response = ChatCompletionResponse(
        id="chatcmpl-" + str(uuid.uuid4()),
        object="chat.completion.chunk",
        created=0,
        model=request.model,
        choices=[Choice(index=0, delta=first_chunk, finish_reason=None)],
        usage=None,
    )
    yield "data: " + first_response.model_dump_json() + "\n\n"

    # 處理原始 response chunk（包含 reasoning_content 同 content）
    async for chunk in response_gen:
        # chunk 係 OpenAI response object，包含 choices[0].delta
        if hasattr(chunk, "choices") and chunk.choices:
            delta = chunk.choices[0].delta

            # 提取 reasoning_content
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                reasoning_chunk = ChoiceDelta(
                    role="assistant", reasoning_content=reasoning, content=None
                )
                reasoning_response = ChatCompletionResponse(
                    id="chatcmpl-" + str(uuid.uuid4()),
                    object="chat.completion.chunk",
                    created=0,
                    model=request.model,
                    choices=[
                        Choice(index=0, delta=reasoning_chunk, finish_reason=None)
                    ],
                    usage=None,
                )
                yield "data: " + reasoning_response.model_dump_json() + "\n\n"

            # 提取 content
            if delta.content:
                final_chunk = ChoiceDelta(role="assistant", content=delta.content)
                final_response = ChatCompletionResponse(
                    id="chatcmpl-" + str(uuid.uuid4()),
                    object="chat.completion.chunk",
                    created=0,
                    model=request.model,
                    choices=[Choice(index=0, delta=final_chunk, finish_reason=None)],
                    usage=None,
                )
                yield "data: " + final_response.model_dump_json() + "\n\n"

    # 發送完成標記（最後一個 chunk 的 finish_reason = "stop"）
    last_chunk = ChoiceDelta(role="assistant", content=None)
    last_response = ChatCompletionResponse(
        id="chatcmpl-" + str(uuid.uuid4()),
        object="chat.completion.chunk",
        created=0,
        model=request.model,
        choices=[Choice(index=0, delta=last_chunk, finish_reason="stop")],
        usage=None,
    )
    yield "data: " + last_response.model_dump_json() + "\n\n"

    # 發送完成標記
    yield "data: [DONE]\n\n"
