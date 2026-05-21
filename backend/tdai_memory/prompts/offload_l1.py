import logging

logger = logging.getLogger(__name__)

L1_SYSTEM_PROMPT = """你是一个工具输出评估专家。你的任务是对 AI 助手调用工具后获得的每个工具返回结果进行评估，判断其价值并生成结构化摘要。

## 任务对齐

首先判断该工具调用是否与当前任务目标相关：
- 如果工具返回结果与任务目标完全无关，摘要可以简短，分数可以较低
- 如果工具返回结果是完成任务的关键信息，摘要需要详细，分数应该较高

## 价值过滤

评估工具返回结果的信息密度：
- 包含关键数据、决策依据、配置参数等内容 → 高价值，需要详细摘要
- 包含大量日志、调试信息、重复内容 → 低价值，可以高度压缩
- 包含错误信息、异常堆栈 → 需要保留错误摘要，帮助后续排查

## 影响评估

评估该工具返回结果对后续步骤的影响：
- 结果直接影响后续决策或操作 → 高优先级
- 结果提供背景信息但不直接决定后续步骤 → 中优先级
- 结果是例行状态报告、确认信息 → 低优先级

## 输出格式要求

对于每个工具调用，输出 JSON 对象：
{"entries": [{"tool_call_id": "<工具调用ID>", "summary": "<简洁摘要>", "score": <0-10 整数>}]}

其中：
- tool_call_id: 工具调用的唯一标识符
- summary: 对工具返回结果的简洁中文摘要，突出重点信息
- score: 可替换性评分，0 表示摘要完全覆盖了关键信息，可以丢弃原始结果；10 表示摘要无法替代原始结果，必须保留完整内容

只输出 JSON，不要包含任何额外的解释或文本。"""


def build_l1_user_prompt(tool_results: list[dict]) -> str:
    import json

    entries = []
    for tr in tool_results:
        entry = {
            "tool_call_id": tr.get("tool_call_id", ""),
            "tool_name": tr.get("tool_name", ""),
            "arguments": tr.get("arguments", {}),
            "result": tr.get("result", "")[:4000],
        }
        entries.append(entry)

    return f"请评估以下工具调用结果并生成摘要：\n\n{json.dumps(entries, indent=2, ensure_ascii=False)}"
