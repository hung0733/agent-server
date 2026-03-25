import json
import logging
import operator
import re
from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from langchain_core.runnables import RunnableConfig
from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import SecretStr

from db.crypto import CryptoManager
from db.dao.llm_endpoint_dao import LLMEndpointDAO
from graph.graph_node import GraphNode
from i18n import _
from tools.tools import get_tools
from utils.tools import Tools

logger = logging.getLogger(__name__)

SUMMARY_TRIGGER_TOKEN = 10000
SUMMARY_USAGE_TOKEN = 5000
CONFIDENCE_THRESHOLD = 0.8

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


# ==========================================
# 1. 狀態定義 (State Management)
# ==========================================
class AgentState(TypedDict):
    summary: str
    # 儲存對話歷史，用 operator.add 確保新 message 會 append 喺尾
    messages: Annotated[Sequence[BaseMessage], operator.add]

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

    messages_to_send: list[BaseMessage] = []
    messages_to_send.append(
        SystemMessage(
            content="""
# System Prompt
You are the central routing core of the J.A.R.V.I.S. system. Your ONLY job is to analyze the user's query and decide which level of AI agent should handle it, and whether deep thinking is required.

You must output STRICTLY IN JSON format. Do not include any explanations, markdown formatting like ```json, or conversational text.

Output Schema:
{"level": <integer 1, 2, or 3>, "think": <boolean>}

Routing Rules (level):
- Level 1 (General & Basic Agent): Handled by a fast 9B model. Covers general conversation, factual questions, standard coding tasks (e.g., writing single scripts, UI components, debugging snippets), and basic agentic workflows using tools (e.g., 1-3 steps of web searching, checking databases).
- Level 2 (Master Agent): Handled by a 27B model. Covers complex, multi-step agentic workflows (e.g., iterative research, deep data analysis), complex project-level coding (e.g., generating multiple connected files, database schema design), and orchestrating multiple tools simultaneously.
- Level 3 (Professor Agent): Handled by a 112B model. Reserved ONLY for extremely complex logical problems, advanced mathematics (e.g., Quantum mechanics), deep system architecture design, or solving intractable bugs.

Thinking Mode (think):
- Set to true ONLY IF the problem requires step-by-step logical deduction, algorithm design, or math. Otherwise, set to false.

# Few-Shot Examples (For context):
User: "幫我上網查下 Apple 最新發佈會講咗咩，然後總結三個重點。"
Output: {"level": 1, "think": false}

User: "幫我寫個 Python script，用 BeautifulSoup 爬取呢個網頁嘅所有圖片並 save 落 local。"
Output: {"level": 1, "think": false}

User: "我段 JavaScript code 有個 TypeError，幫我 debug 吓：[code snippet]"
Output: {"level": 1, "think": true}

User: "幫我爬取對手網站最新嘅產品價格，然後連去我哋個 PostgreSQL DB 做對比，最後 gen 份 Markdown 報告並 send email 俾老細。"
Output: {"level": 2, "think": false}

User: "請幫我用 Rust 寫一個高效能嘅非同步 Web Server，包含 Connection Pool、JWT Authentication 同埋 Rate Limiting Middleware。"
Output: {"level": 2, "think": true}

User: "推導一下黑洞事件視界邊緣嘅霍金輻射方程式。"
Output: {"level": 3, "think": true}
"""
        )
    )

    summary = state.get("summary", "")
    if summary:
        messages_to_send.append(
            AIMessage(
                content=_("以下是過去對話的重點總結，請作為背景記憶參考：\n%s")
                % summary
            )
        )

    messages_to_send += state["messages"]

    model: BaseChatModel = models.rte_model
    temperature = 0.0
    model = model.bind(
        temperature=temperature,
        top_p=top_p,
        presence_penalty=presence_penalty,
        extra_body=extra_body,
    )  # type: ignore

    # 呼叫模型 (用 ainvoke 獲取完整回應)
    response = await model.ainvoke(messages_to_send)
    raw_content = response.content.strip()  # type: ignore

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
        # Fallback (補底機制)：如果 4B 發神經出唔到 JSON，預設交俾 9B 處理
        logger.warning(_("⚠️ [Router JSON 解析失敗]: %s | Error: %s"), raw_content, e)
        routing_level = 1
        think_mode = False
        logger.info(
            _("-> [Router 補底啟動]: 強制派去 Level=%d, Think=%s"),
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
    db_tools = await get_tools(agent_db_id)

    messages_to_send: list[BaseMessage] = []
    messages_to_send.append(SystemMessage(content=sys_prompt))

    summary = state.get("summary", "")
    if summary:
        messages_to_send.append(
            AIMessage(
                content=_("以下是過去對話的重點總結，請作為背景記憶參考：\n%s")
                % summary
            )
        )

    messages_to_send += state["messages"]

    models = model_set.level[1]
    logger.debug(_("[Level 1] 找到 %d 個可用模型"), len(models))
    for model_dto in models:
        try:
            # Handle API key - use placeholder for local models without auth
            if model_dto.api_key_encrypted:
                api_key = CryptoManager().decrypt(model_dto.api_key_encrypted)
            else:
                api_key = "EMPTY"  # Placeholder for local models

            model: BaseChatModel = ChatOpenAI(
                base_url=model_dto.base_url,
                api_key=SecretStr(api_key),
                model=model_dto.model_name,
                streaming=True,
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
            response = await model.ainvoke(messages_to_send)

            Tools.start_async_task(
                LLMEndpointDAO.record_feedback(model_dto.id, success=True)
            )

            return {"messages": [response]}
        except Exception as exc:
            # Handle Fail Model
            logger.error(
                _("[Level 1] 模型 %s 呼叫失敗: %s"), model_dto.model_name, exc, exc_info=True
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
    db_tools = await get_tools(agent_db_id)

    messages_to_send: list[BaseMessage] = []
    messages_to_send.append(SystemMessage(content=sys_prompt))

    summary = state.get("summary", "")
    if summary:
        messages_to_send.append(
            AIMessage(
                content=_("以下是過去對話的重點總結，請作為背景記憶參考：\n%s")
                % summary
            )
        )

    messages_to_send += state["messages"]

    models = model_set.level[2]
    logger.debug(_("[Level 2] 找到 %d 個可用模型"), len(models))
    for model_dto in models:
        try:
            # Handle API key - use placeholder for local models without auth
            if model_dto.api_key_encrypted:
                api_key = CryptoManager().decrypt(model_dto.api_key_encrypted)
            else:
                api_key = "EMPTY"  # Placeholder for local models

            model: BaseChatModel = ChatOpenAI(
                base_url=model_dto.base_url,
                api_key=SecretStr(api_key),
                model=model_dto.model_name,
                streaming=True,
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

            Tools.start_async_task(
                LLMEndpointDAO.record_feedback(model_dto.id, success=True)
            )

            return {"messages": [response]}
        except Exception as exc:
            # Handle Fail Model
            logger.error(
                _("[Level 2] 模型 %s 呼叫失敗: %s"), model_dto.model_name, exc, exc_info=True
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
    db_tools = await get_tools(agent_db_id)

    messages_to_send: list[BaseMessage] = []
    messages_to_send.append(SystemMessage(content=sys_prompt))

    summary = state.get("summary", "")
    if summary:
        messages_to_send.append(
            AIMessage(
                content=_("以下是過去對話的重點總結，請作為背景記憶參考：\n%s")
                % summary
            )
        )

    messages_to_send += state["messages"]

    models = model_set.level[3]
    logger.debug(_("[Level 3] 找到 %d 個可用模型"), len(models))
    for model_dto in models:
        try:
            # Handle API key - use placeholder for local models without auth
            if model_dto.api_key_encrypted:
                api_key = CryptoManager().decrypt(model_dto.api_key_encrypted)
            else:
                api_key = "EMPTY"  # Placeholder for local models

            model: BaseChatModel = ChatOpenAI(
                base_url=model_dto.base_url,
                api_key=SecretStr(api_key),
                model=model_dto.model_name,
                streaming=True,
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

            Tools.start_async_task(
                LLMEndpointDAO.record_feedback(model_dto.id, success=True)
            )

            return {"messages": [response]}
        except Exception as exc:
            # Handle Fail Model
            logger.error(
                _("[Level 3] 模型 %s 呼叫失敗: %s"), model_dto.model_name, exc, exc_info=True
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
    db_tools = await get_tools(agent_db_id)

    # 3. 即場初始化 LangGraph 內建嘅 ToolNode
    # ⚠️ 注意：只入 db_tools！唔好入 `submit_final_answer`，因為嗰個係假 tool 用來截胡嘅
    tool_executor = ToolNode(db_tools)

    # 4. 執行 ToolNode (佢會自動對應 state 裡面嘅 tool_calls 去 run，並回傳 ToolMessage)
    result = await tool_executor.ainvoke(state, config)

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
