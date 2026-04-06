from datetime import datetime
import json
import logging
import operator
import re
from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage, RemoveMessage, ToolMessage
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END
from langchain_core.runnables import RunnableConfig
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import SecretStr

from db.crypto import CryptoManager
from db.dao.llm_endpoint_dao import LLMEndpointDAO
from graph.graph_node import GraphNode
from i18n import _
from models.llm import build_streaming_chat_openai
from tools.tools import get_tools
from utils.tools import Tools

logger = logging.getLogger(__name__)

SUMMARY_TRIGGER_TOKEN = 10000
SUMMARY_USAGE_TOKEN = 5000
CONFIDENCE_THRESHOLD = 0.8
MODEL_INPUT_TOKEN_BUDGET = 20000
REACT_STEP_SUMMARY_TRIGGER_TOKEN = 12000
REACT_STEP_SUMMARY_KEEP_MESSAGES = 6
REACT_SUMMARY_TOKEN_BUDGET = 4000

# 定義「提交答案」嘅 System Tool (用嚟攞信心評分)
SUBMIT_TOOL = {
    "name": "submit_final_answer",
    "description": "When you have the final answer, use this tool to submit it along with your confidence score (0.0 to 1.0).",
    "parameters": {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "confidence_score": {"type": "number"},
        },
        "required": ["answer", "confidence_score"],
    },
}


def _message_token_count(message: BaseMessage) -> int:
    return Tools.get_token_count(message.content) + 16


def _build_messages_with_token_budget(
    sys_prompt: str,
    summary: str,
    messages: Sequence[BaseMessage],
    max_tokens: int = MODEL_INPUT_TOKEN_BUDGET,
    assistant_prefill: BaseMessage | None = None,
    label: str = "prompt",
) -> list[BaseMessage]:
    messages_to_send: list[BaseMessage] = [SystemMessage(content=sys_prompt)]
    used_tokens = _message_token_count(messages_to_send[0])
    summary_included = False
    prefill_included = False

    if summary:
        summary_message = AIMessage(
            content=_("以下是過去對話的重點總結，請作為背景記憶參考：\n%s") % summary
        )
        summary_tokens = _message_token_count(summary_message)
        if used_tokens + summary_tokens <= max_tokens:
            messages_to_send.append(summary_message)
            used_tokens += summary_tokens
            summary_included = True
        else:
            logger.warning(
                _("摘要過長，已略過以保留對話上下文: tokens=%d budget=%d"),
                summary_tokens,
                max_tokens,
            )

    filtered_messages = [m for m in messages if not isinstance(m, RemoveMessage)]
    original_message_count = len(filtered_messages)
    estimated_tokens_before_trim = used_tokens + sum(
        _message_token_count(message) for message in filtered_messages
    )
    selected_messages: list[BaseMessage] = []
    for message in reversed(filtered_messages):
        message_tokens = _message_token_count(message)
        if used_tokens + message_tokens > max_tokens:
            continue
        selected_messages.append(message)
        used_tokens += message_tokens

    messages_to_send.extend(reversed(selected_messages))

    if assistant_prefill is not None:
        prefill_tokens = _message_token_count(assistant_prefill)
        if used_tokens + prefill_tokens <= max_tokens:
            messages_to_send.append(assistant_prefill)
            used_tokens += prefill_tokens
            prefill_included = True
        else:
            logger.warning(
                _("assistant prefill 超出 token budget，已略過: tokens=%d budget=%d"),
                prefill_tokens,
                max_tokens,
            )

    logger.debug(
        _(
            "Prompt budget [%s]: budget=%d estimated_before=%d estimated_after=%d original_messages=%d sent_messages=%d trimmed_messages=%d summary_included=%s assistant_prefill_included=%s"
        ),
        label,
        max_tokens,
        estimated_tokens_before_trim,
        used_tokens,
        original_message_count,
        len(selected_messages),
        original_message_count - len(selected_messages),
        summary_included,
        prefill_included,
    )

    return messages_to_send


def _task_id_from_config(config: RunnableConfig) -> str | None:
    configurable = config.get("configurable", {})  # type: ignore[arg-type]
    if not isinstance(configurable, dict):
        return None

    args = configurable.get("args")
    if not isinstance(args, dict):
        return None

    task_id = args.get("task_id")
    if task_id in (None, ""):
        return None

    task_id_str = str(task_id).strip()
    if task_id_str:
        return task_id_str
    return None


def _message_summary_line(message: BaseMessage) -> str:
    content = str(message.content).strip()
    if len(content) > 240:
        content = content[:240] + "..."

    if isinstance(message, HumanMessage):
        return f"User: {content}"
    if isinstance(message, ToolMessage):
        tool_name = getattr(message, "name", "tool") or "tool"
        return f"Tool result {tool_name}: {content}"
    if isinstance(message, AIMessage):
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            tool_descriptions = []
            for tool_call in tool_calls[:3]:
                tool_name = tool_call.get("name", "tool")
                tool_args = json.dumps(tool_call.get("args", {}), ensure_ascii=False)
                if len(tool_args) > 120:
                    tool_args = tool_args[:120] + "..."
                tool_descriptions.append(f"{tool_name}({tool_args})")
            more = " ..." if len(tool_calls) > 3 else ""
            return f"Tool call {'; '.join(tool_descriptions)}{more}"
        return f"Assistant: {content}"
    return f"Message: {content}"


def _trim_summary_text(summary: str, max_tokens: int = REACT_SUMMARY_TOKEN_BUDGET) -> str:
    lines = [line for line in summary.splitlines() if line.strip()]
    if not lines:
        return ""

    kept: list[str] = []
    used_tokens = 0
    for line in reversed(lines):
        line_tokens = Tools.get_token_count(line)
        if kept and used_tokens + line_tokens > max_tokens:
            break
        kept.append(line)
        used_tokens += line_tokens
    return "\n".join(reversed(kept))


def _compact_react_state_if_needed(
    summary: str,
    existing_messages: Sequence[BaseMessage],
    new_messages: Sequence[BaseMessage],
    max_tokens: int = REACT_STEP_SUMMARY_TRIGGER_TOKEN,
    keep_last_messages: int = REACT_STEP_SUMMARY_KEEP_MESSAGES,
) -> dict[str, object] | None:
    filtered_existing = [m for m in existing_messages if not isinstance(m, RemoveMessage)]
    filtered_new = [m for m in new_messages if not isinstance(m, RemoveMessage)]
    projected_tokens = Tools.get_token_count(summary) + sum(
        _message_token_count(message) for message in [*filtered_existing, *filtered_new]
    )

    if projected_tokens <= max_tokens or len(filtered_existing) <= keep_last_messages:
        return None

    messages_to_summarize = filtered_existing[:-keep_last_messages]
    if not messages_to_summarize:
        return None

    remove_messages: list[RemoveMessage] = []
    for message in messages_to_summarize:
        message_id = getattr(message, "id", None)
        if not message_id:
            logger.warning(_("ReAct summary skipped because message lacks id: %s"), type(message).__name__)
            return None
        remove_messages.append(RemoveMessage(id=message_id))

    summary_lines: list[str] = []
    if summary.strip():
        summary_lines.append(summary.strip())
    summary_lines.append(_("以下為較早前 ReAct 步驟摘要："))
    summary_lines.extend(f"- {_message_summary_line(message)}" for message in messages_to_summarize)
    updated_summary = _trim_summary_text("\n".join(summary_lines))

    logger.info(
        _("ReAct context compacted: removed=%d kept=%d new=%d tokens_before=%d"),
        len(messages_to_summarize),
        keep_last_messages,
        len(filtered_new),
        projected_tokens,
    )
    return {
        "summary": updated_summary,
        "messages": [*remove_messages, *filtered_new],
    }


# ==========================================
# 1. 狀態定義 (State Management)
# ==========================================
class AgentState(TypedDict):
    summary: str
    # 儲存對話歷史，用 add_messages 確保新 message 會 append 喺尾，並支援 RemoveMessage
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Routing 與控制參數
    routing_level: int  # 1, 2, or 3
    think_mode: bool  # 是否開啟思考模式

    # 信心評分 (Confidence Scores)
    l1_score: float
    l2_score: float


# ==========================================
# 2. 節點定義 (Nodes - Qwen Models)
# ==========================================
async def router_node(
    state: AgentState, config: RunnableConfig
) -> dict[str, int | bool]:
    """Qwen3.5-4B: 負責快速意圖識別及派單"""
    logger.debug(_("[Router 4B] 分析緊問題..."))

    models, temperature, top_p, presence_penalty, extra_body = GraphNode.get_model(
        config, False
    )

    messages_to_send = _build_messages_with_token_budget(
        sys_prompt="""You are a routing classifier. Output ONLY a single line of JSON. No explanations, no markdown, no extra text.

Format: {"level": 1, "think": false}

Rules:
- Level 1 (General & Fast Agent): Handled by a 35B MoE model. Covers general conversation, factual questions, standard coding tasks, analyzing structured data (e.g., Excel, CSV, schedules, itineraries), and basic agentic workflows using tools.
- Level 2 (Master Agent): Handled by a 27B Dense model. Covers complex, multi-step agentic workflows (e.g., iterative research, deep data analysis), complex project-level coding, and orchestrating multiple tools simultaneously.
- Level 3 (Professor Agent): Handled by a 112B model. Reserved ONLY for extremely complex logical problems, advanced mathematics, or deep system architecture design.
- think: true only for math/logic/algorithms, otherwise false

Examples:
User: "幫我上網查下 Apple 最新發佈會講咗咩，然後總結三個重點。"
{"level": 1, "think": false}

User: "我段 JavaScript code 有個 TypeError，幫我 debug 吓：[code snippet]"
{"level": 1, "think": true}

User: "幫我爬取對手網站最新嘅產品價格，然後連去我哋個 PostgreSQL DB 做對比，最後 gen 份 Markdown 報告並 send email 俾老細。"
{"level": 2, "think": false}

User: "推導一下黑洞事件視界邊緣嘅霍金輻射方程式。"
{"level": 3, "think": true}

CRITICAL: Your entire response must be ONLY the JSON object. Nothing else.
""",
        summary=state.get("summary", ""),
        messages=state["messages"],
        assistant_prefill=AIMessage(content='{"level":'),
        label="router",
    )

    model: BaseChatModel = models.rte_model
    temperature = 0.0

    # Try to enable JSON mode if supported
    bind_params = {
        "temperature": temperature,
        "top_p": top_p,
        "presence_penalty": presence_penalty,
        "extra_body": extra_body,
    }

    # Add JSON mode for supported models
    try:
        bind_params["response_format"] = {"type": "json_object"}
    except Exception:
        pass  # Model doesn't support response_format

    model = model.bind(**bind_params)  # type: ignore

    # 呼叫模型 (用 ainvoke 獲取完整回應)
    response = await model.ainvoke(messages_to_send)
    raw_content = response.content.strip()  # type: ignore

    # Prepend the prefix back to make it valid JSON
    if not raw_content.startswith("{"):
        raw_content = '{"level":' + raw_content

    # --- 關鍵防護機制 (Defensive Programming) ---
    # 4B 模型有時會發癲照出 ```json ... ```，我哋用 Regex 抹走佢
    if raw_content.startswith("```"):
        raw_content = re.sub(
            r"^```(?:json)?\n?|```$", "", raw_content, flags=re.MULTILINE
        ).strip()

    try:
        # 嘗試 Parse JSON
        parsed_data = json.loads(raw_content)
        routing_level = int(parsed_data.get("level", 1))
        think_mode = bool(parsed_data.get("think", False))
        logger.info(
            _("-> [Router 決定]: Level=%d, Think=%s"), routing_level, think_mode
        )

    except (json.JSONDecodeError, ValueError) as e:
        # Fallback: Try to extract JSON from text
        json_match = re.search(r'\{[^}]*"level"\s*:\s*\d[^}]*\}', raw_content)
        if json_match:
            try:
                parsed_data = json.loads(json_match.group(0))
                routing_level = int(parsed_data.get("level", 1))
                think_mode = bool(parsed_data.get("think", False))
                logger.info(
                    _("-> [Router 決定 (抽取)]: Level=%d, Think=%s"),
                    routing_level,
                    think_mode,
                )
            except Exception:
                # Final fallback: default to Level 1
                preview = raw_content[:100] + ("..." if len(raw_content) > 100 else "")
                logger.warning(_("⚠️ [Router 返回非 JSON]: %s"), preview)
                routing_level = 1
                think_mode = False
                logger.info(
                    _("-> [Router 補底]: Level=%d, Think=%s"),
                    routing_level,
                    think_mode,
                )
        else:
            # Final fallback: default to Level 1
            preview = raw_content[:100] + ("..." if len(raw_content) > 100 else "")
            logger.warning(_("⚠️ [Router 返回非 JSON]: %s"), preview)
            routing_level = 1
            think_mode = False
            logger.info(
                _("-> [Router 補底]: Level=%d, Think=%s"),
                routing_level,
                think_mode,
            )

    # 注意：我哋唔 return "messages"，避免 JSON 污染對話 Context
    return {"routing_level": routing_level, "think_mode": think_mode}


async def level_1_node(
    state: AgentState, config: RunnableConfig
) -> dict[str, list[BaseMessage]]:
    """Qwen3.5-9B: 處理日常任務 (60t/s) 並自我評分"""
    logger.debug(_("[Level 1 - 9B] 處理中..."))
    agent_db_id: str = config["configurable"].get("agent_db_id", "")  # type: ignore
    sys_prompt: str = config["configurable"].get("sys_prompt", "")  # type: ignore

    model_set, temperature, top_p, presence_penalty, extra_body = GraphNode.get_model(
        config, state.get("think_mode", False)
    )

    # 2. 用你寫好嘅 DB Loader 攞 Tools
    db_tools = await get_tools(agent_db_id, task_id=_task_id_from_config(config))
    logger.info(
        _("載入了 %d 個工具: %s"),
        len(db_tools),
        [t.name for t in db_tools] if db_tools else "無",
    )

    messages_to_send = _build_messages_with_token_budget(
        sys_prompt=sys_prompt,
        summary=state.get("summary", ""),
        messages=state["messages"],
        label="level_1",
    )

    models = model_set.level[1]
    logger.debug(_("[Level 1] 找到 %d 個可用模型"), len(models))
    for model_dto in models:
        try:
            # Handle API key - use placeholder for local models without auth
            if model_dto.api_key_encrypted:
                api_key = CryptoManager().decrypt(model_dto.api_key_encrypted)
            else:
                api_key = "EMPTY"  # Placeholder for local models

            model: BaseChatModel = build_streaming_chat_openai(
                base_url=model_dto.base_url,
                api_key=SecretStr(api_key),
                model_name=model_dto.model_name,
            )

            # 4. 綁定 Tools 落 9B
            model = model.bind_tools(db_tools + [SUBMIT_TOOL])  # type: ignore

            model = model.bind(
                temperature=temperature,
                top_p=top_p,
                presence_penalty=presence_penalty,
                extra_body=extra_body,
            )  # type: ignore

            # 5. Invoke 模型
            response: AIMessage = await model.ainvoke(messages_to_send)

            # 驗證 response content 唔好係空（但 tool calls 係有效嘅）
            has_content = response.content and str(response.content).strip()
            has_tool_calls = hasattr(response, "tool_calls") and len(response.tool_calls) > 0  # type: ignore

            if not has_content and not has_tool_calls:
                logger.warning(
                    _("[Level 1] 模型 %s 返回空 content 且無 tool calls，跳過呢個回應"),
                    model_dto.model_name,
                )
                continue

            Tools.start_async_task(
                LLMEndpointDAO.record_feedback(model_dto.id, success=True)
            )

            response.additional_kwargs["datetime"] = datetime.now()
            response.additional_kwargs["llm_endpoint_id"] = str(model_dto.id)
            response.additional_kwargs["model_name"] = model_dto.model_name

            return {"messages": [response]}
        except Exception as exc:
            # Handle Fail Model
            logger.error(
                _("[Level 1] 模型 %s 呼叫失敗: %s"),
                model_dto.model_name,
                exc,
                exc_info=True,
            )
            Tools.start_async_task(
                LLMEndpointDAO.record_feedback(model_dto.id, success=False)
            )

    # 如果所有模型都失敗，拋出異常
    if len(models) == 0:
        raise RuntimeError(_("沒有可用的 Level 1 模型"))
    raise RuntimeError(_("所有 Level 1 模型均呼叫失敗"))


async def level_2_node(
    state: AgentState, config: RunnableConfig
) -> dict[str, list[BaseMessage]]:
    """Qwen3.5-27B: 執行 Tools, Master Level 任務或補底"""
    logger.debug(_("[Level 2 - 27B] 接手處理 / Call Tools 中..."))
    agent_db_id: str = config["configurable"].get("agent_db_id", "")  # type: ignore
    sys_prompt: str = config["configurable"].get("sys_prompt", "")  # type: ignore

    model_set, temperature, top_p, presence_penalty, extra_body = GraphNode.get_model(
        config, state.get("think_mode", False)
    )

    # 2. 用你寫好嘅 DB Loader 攞 Tools
    db_tools = await get_tools(agent_db_id, task_id=_task_id_from_config(config))
    logger.info(
        _("載入了 %d 個工具: %s"),
        len(db_tools),
        [t.name for t in db_tools] if db_tools else "無",
    )

    messages_to_send = _build_messages_with_token_budget(
        sys_prompt=sys_prompt,
        summary=state.get("summary", ""),
        messages=state["messages"],
        label="level_2",
    )

    models = model_set.level[2]
    logger.debug(_("[Level 2] 找到 %d 個可用模型"), len(models))
    for model_dto in models:
        try:
            # Handle API key - use placeholder for local models without auth
            if model_dto.api_key_encrypted:
                api_key = CryptoManager().decrypt(model_dto.api_key_encrypted)
            else:
                api_key = "EMPTY"  # Placeholder for local models

            model: BaseChatModel = build_streaming_chat_openai(
                base_url=model_dto.base_url,
                api_key=SecretStr(api_key),
                model_name=model_dto.model_name,
            )

            # 4. 綁定 Tools 落 27B
            model = model.bind_tools(db_tools + [SUBMIT_TOOL])  # type: ignore

            model = model.bind(
                temperature=temperature,
                top_p=top_p,
                presence_penalty=presence_penalty,
                extra_body=extra_body,
            )  # type: ignore

            # 5. Invoke 模型
            response = await model.ainvoke(messages_to_send)

            # 驗證 response content 唔好係空（但 tool calls 係有效嘅）
            has_content = response.content and str(response.content).strip()
            has_tool_calls = hasattr(response, "tool_calls") and len(response.tool_calls) > 0  # type: ignore

            if not has_content and not has_tool_calls:
                logger.warning(
                    _("[Level 2] 模型 %s 返回空 content 且無 tool calls，跳過呢個回應"),
                    model_dto.model_name,
                )
                continue

            Tools.start_async_task(
                LLMEndpointDAO.record_feedback(model_dto.id, success=True)
            )

            response.additional_kwargs["datetime"] = datetime.now()
            response.additional_kwargs["llm_endpoint_id"] = str(model_dto.id)
            response.additional_kwargs["model_name"] = model_dto.model_name

            return {"messages": [response]}
        except Exception as exc:
            # Handle Fail Model
            logger.error(
                _("[Level 2] 模型 %s 呼叫失敗: %s"),
                model_dto.model_name,
                exc,
                exc_info=True,
            )
            Tools.start_async_task(
                LLMEndpointDAO.record_feedback(model_dto.id, success=False)
            )

    # 如果所有模型都失敗，拋出異常
    if len(models) == 0:
        raise RuntimeError(_("沒有可用的 Level 2 模型"))
    raise RuntimeError(_("所有 Level 2 模型均呼叫失敗"))


async def level_3_node(
    state: AgentState, config: RunnableConfig
) -> dict[str, list[BaseMessage]]:
    """Qwen3.5-112B: 終極大佬，處理 Professor Level 難題"""
    logger.debug(_("[Level 3 - 112B] 大佬出馬，進行深度推理..."))
    agent_db_id: str = config["configurable"].get("agent_db_id", "")  # type: ignore
    sys_prompt: str = config["configurable"].get("sys_prompt", "")  # type: ignore

    model_set, temperature, top_p, presence_penalty, extra_body = GraphNode.get_model(
        config, state.get("think_mode", False)
    )

    # 2. 用你寫好嘅 DB Loader 攞 Tools
    db_tools = await get_tools(agent_db_id, task_id=_task_id_from_config(config))
    logger.info(
        _("載入了 %d 個工具: %s"),
        len(db_tools),
        [t.name for t in db_tools] if db_tools else "無",
    )

    messages_to_send = _build_messages_with_token_budget(
        sys_prompt=sys_prompt,
        summary=state.get("summary", ""),
        messages=state["messages"],
        label="level_3",
    )

    models = model_set.level[3]
    logger.debug(_("[Level 3] 找到 %d 個可用模型"), len(models))
    for model_dto in models:
        try:
            # Handle API key - use placeholder for local models without auth
            if model_dto.api_key_encrypted:
                api_key = CryptoManager().decrypt(model_dto.api_key_encrypted)
            else:
                api_key = "EMPTY"  # Placeholder for local models

            model: BaseChatModel = build_streaming_chat_openai(
                base_url=model_dto.base_url,
                api_key=SecretStr(api_key),
                model_name=model_dto.model_name,
            )

            # 4. 綁定 Tools 落 122B
            model = model.bind_tools(db_tools)  # type: ignore

            model = model.bind(
                temperature=temperature,
                top_p=top_p,
                presence_penalty=presence_penalty,
                extra_body=extra_body,
            )  # type: ignore

            # 5. Invoke 模型
            response = await model.ainvoke(messages_to_send)

            # 驗證 response content 唔好係空（但 tool calls 係有效嘅）
            has_content = response.content and str(response.content).strip()
            has_tool_calls = hasattr(response, "tool_calls") and len(response.tool_calls) > 0  # type: ignore

            if not has_content and not has_tool_calls:
                logger.warning(
                    _("[Level 3] 模型 %s 返回空 content 且無 tool calls，跳過呢個回應"),
                    model_dto.model_name,
                )
                continue

            Tools.start_async_task(
                LLMEndpointDAO.record_feedback(model_dto.id, success=True)
            )

            response.additional_kwargs["datetime"] = datetime.now()
            response.additional_kwargs["llm_endpoint_id"] = str(model_dto.id)
            response.additional_kwargs["model_name"] = model_dto.model_name

            return {"messages": [response]}
        except Exception as exc:
            # Handle Fail Model
            logger.error(
                _("[Level 3] 模型 %s 呼叫失敗: %s"),
                model_dto.model_name,
                exc,
                exc_info=True,
            )
            Tools.start_async_task(
                LLMEndpointDAO.record_feedback(model_dto.id, success=False)
            )

    # 如果所有模型都失敗，拋出異常
    if len(models) == 0:
        raise RuntimeError(_("沒有可用的 Level 3 模型"))
    raise RuntimeError(_("所有 Level 3 模型均呼叫失敗"))


# ==========================================
# 3. 條件路由邏輯 (Conditional Edges)
# ==========================================
def route_from_start(state: AgentState, config: RunnableConfig) -> str:
    """根據 Router 決定派去邊個 Node"""
    level = state.get("routing_level", 1)
    if level == 3:
        return "Level_3"
    elif level == 2:
        return "Level_2"
    else:
        return "Level_1"


def check_l1_confidence(state: AgentState, config: RunnableConfig) -> str:
    """檢查 9B 嘅信心評分"""
    messages = state.get("messages", [])
    if not messages:
        return END

    last_message = messages[-1]

    # 檢查是否有 Tool Calls
    if hasattr(last_message, "tool_calls") and len(last_message.tool_calls) > 0:  # type: ignore
        has_submit_tool = False
        for tc in getattr(last_message, "tool_calls", []):
            if tc.get("name") == "submit_final_answer":
                # 提取信心評分並儲存 (注意：LangGraph 會自動合併返回的 state)
                score = float(tc.get("args", {}).get("confidence_score", 1.0))
                logger.debug(_("[L1 評分]: %s"), score)
                has_submit_tool = True
                # 檢查分數是否足夠
                if score >= CONFIDENCE_THRESHOLD:
                    return END
                return "Level_2"

        # 如果有其他 tool calls（不是 submit_final_answer），去執行 Tools
        if not has_submit_tool:
            return "Level_1_Tools"

    # 如果無 Tool Calls，代表已經答完，預設高信心
    return END


def check_l2_confidence(state: AgentState, config: RunnableConfig) -> str:
    """檢查 27B 嘅信心評分"""
    messages = state.get("messages", [])
    if not messages:
        return END

    last_message = messages[-1]

    # 檢查是否有 Tool Calls
    if hasattr(last_message, "tool_calls") and len(last_message.tool_calls) > 0:  # type: ignore
        has_submit_tool = False
        for tc in getattr(last_message, "tool_calls", []):
            if tc.get("name") == "submit_final_answer":
                # 提取信心評分並儲存
                score = float(tc.get("args", {}).get("confidence_score", 1.0))
                logger.debug(_("[L2 評分]: %s"), score)
                has_submit_tool = True
                # 檢查分數是否足夠
                if score >= CONFIDENCE_THRESHOLD:
                    return END
                return "Level_3"  # 仲係唔夠分，終極 Escalate 俾 112B

        # 如果有其他 tool calls（不是 submit_final_answer），去執行 Tools
        if not has_submit_tool:
            return "Level_2_Tools"

    # 如果無 Tool Calls，代表已經答完，預設高信心
    return END


# 定義動態 Tool Node Wrapper
async def dynamic_tool_node(
    state: AgentState, config: RunnableConfig
) -> dict[str, list[BaseMessage]]:
    """執行 DB 動態載入的 Tools"""
    logger.info(_("[Tool Node] 準備執行工具..."))

    # 1. 由 config 攞 agent_db_id
    agent_db_id: str = config["configurable"].get("agent_db_id", "")  # type: ignore

    # 2. 實時去 DB 攞最新嘅 Tools
    db_tools = await get_tools(agent_db_id, task_id=_task_id_from_config(config))

    # 3. 即場初始化 LangGraph 內建嘅 ToolNode
    # ⚠️ 注意：只入 db_tools！唔好入 `submit_final_answer`，因為嗰個係假 tool 用來截胡嘅
    tool_executor = ToolNode(db_tools)

    # 4. 執行 ToolNode (佢會自動對應 state 裡面嘅 tool_calls 去 run，並回傳 ToolMessage)
    result = await tool_executor.ainvoke(state, config)

    compacted = _compact_react_state_if_needed(
        summary=state.get("summary", ""),
        existing_messages=state.get("messages", []),
        new_messages=result.get("messages", []),
    )
    if compacted is not None:
        return compacted

    return result


# ==========================================
# 4. 構建 Graph (Build the Graph)
# ==========================================
workflow = StateGraph(AgentState)

# 加入所有 Nodes
workflow.add_node("Router", router_node)
workflow.add_node("Level_1", level_1_node)
workflow.add_node("Level_2", level_2_node)
workflow.add_node("Level_3", level_3_node)
workflow.add_node("Level_1_Tools", dynamic_tool_node)
workflow.add_node("Level_2_Tools", dynamic_tool_node)
workflow.add_node("tools", dynamic_tool_node)

# 設定邊界 (Edges) 與 Flow
workflow.add_edge(START, "Router")

# Router 的條件分支
workflow.add_conditional_edges(
    "Router",
    route_from_start,
    {"Level_1": "Level_1", "Level_2": "Level_2", "Level_3": "Level_3"},
)

# L1 的條件分支
workflow.add_conditional_edges(
    "Level_1",
    check_l1_confidence,
    {"Level_1_Tools": "Level_1_Tools", END: END, "Level_2": "Level_2"},
)

workflow.add_edge("Level_1_Tools", "Level_1")

# L2 的條件分支
workflow.add_conditional_edges(
    "Level_2",
    check_l2_confidence,
    {"Level_2_Tools": "Level_2_Tools", END: END, "Level_3": "Level_3"},
)

workflow.add_edge("Level_2_Tools", "Level_2")

# L3 跑完直接完結
workflow.add_conditional_edges(
    "Level_3",
    tools_condition,
)

workflow.add_edge("tools", "Level_3")

# 編譯 Graph
graph = workflow.compile()
