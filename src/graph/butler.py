import logging
import operator
from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
from langgraph.graph import StateGraph, START, END

from i18n import _

logger = logging.getLogger(__name__)


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
    involves_secrets: bool

    # 信心評分 (Confidence Scores)
    l1_score: float
    l2_score: float


# ==========================================
# 2. 節點定義 (Nodes - Qwen Models)
# ==========================================
def router_node(state: AgentState) -> dict:
    """Qwen3.5-4B: 負責快速意圖識別及派單"""
    logger.info(_("[Router 4B] 分析緊問題..."))
    # TODO: Call 4B Model (Enforce JSON output)
    # Mocking router decision: 假設判斷為 Level 1 任務
    return {"routing_level": 1, "think_mode": False}


def level_1_node(state: AgentState) -> dict:
    """Qwen3.5-9B: 處理日常任務 (60t/s) 並自我評分"""
    logger.info(_("[Level 1 - 9B] 處理中..."))
    # TODO: Call 9B Model (Prompt 需強制輸出評分)

    # Mocking 9B output: 假設佢遇到唔識嘅嘢，俾自己 0.6 分
    mock_score = 0.6
    mock_msg = AIMessage(content="我初步覺得係咁，但我唔係百分百肯定...")

    return {"l1_score": mock_score, "messages": [mock_msg]}


def level_2_node(state: AgentState) -> dict:
    """Qwen3.5-27B: 執行 Tools, Master Level 任務或補底"""
    logger.info(_("[Level 2 - 27B] 接手處理 / Call Tools 中..."))
    # TODO: Call 27B Model (Bind tools: WebSearch, DB, etc.)

    # Mocking 27B output: 假設 Call 完 Tool 都係得 0.7 分
    mock_score = 0.7
    mock_msg = AIMessage(content="我幫你查過網頁，搵到啲線索，但未有最準確答案。")

    return {"l2_score": mock_score, "messages": [mock_msg]}


def level_3_node(state: AgentState) -> dict:
    """Qwen3.5-112B: 終極大佬，處理 Professor Level 難題"""
    logger.info(_("[Level 3 - 112B] 大佬出馬，進行深度推理..."))
    # TODO: Call 112B Model
    mock_msg = AIMessage(content="經過深度邏輯鏈分析，最終正確答案如下：...")
    return {"messages": [mock_msg]}


# ==========================================
# 3. 條件路由邏輯 (Conditional Edges)
# ==========================================
def route_from_start(state: AgentState) -> str:
    """根據 Router 決定派去邊個 Node"""
    level = state.get("routing_level", 1)
    if level == 3:
        return "Level_3"
    elif level == 2:
        return "Level_2"
    else:
        return "Level_1"


def check_l1_confidence(state: AgentState) -> str:
    """檢查 9B 嘅信心評分"""
    score = state.get("l1_score", 1.0)
    logger.debug(_("[L1 評分]: %s"), score)
    if score >= 0.8:
        return END
    return "Level_2"  # 唔夠分，Escalate 俾 27B


def check_l2_confidence(state: AgentState) -> str:
    """檢查 27B 嘅信心評分"""
    score = state.get("l2_score", 1.0)
    logger.debug(_("[L2 評分]: %s"), score)
    if score >= 0.8:
        return END
    return "Level_3"  # 仲係唔夠分，終極 Escalate 俾 112B


# ==========================================
# 4. 構建 Graph (Build the Graph)
# ==========================================
workflow = StateGraph(AgentState)

# 加入所有 Nodes
workflow.add_node("Router", router_node)
workflow.add_node("Level_1", level_1_node)
workflow.add_node("Level_2", level_2_node)
workflow.add_node("Level_3", level_3_node)

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
    "Level_1", check_l1_confidence, {END: END, "Level_2": "Level_2"}
)

# L2 的條件分支
workflow.add_conditional_edges(
    "Level_2", check_l2_confidence, {END: END, "Level_3": "Level_3"}
)

# L3 跑完直接完結
workflow.add_edge("Level_3", END)

# 編譯 Graph
graph = workflow.compile()
