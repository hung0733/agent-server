import json
import logging
import openai

logger = logging.getLogger(__name__)


async def summarize_tool_result(
    tool_name: str,
    tool_input: dict,
    result_text: str,
    llm_client: openai.AsyncOpenAI,
    config,
) -> tuple[str, int]:
    truncated = result_text[:4000]
    system_prompt = (
        "You are a tool output summarizer. Given a tool call and its result, produce a concise summary "
        "and a replaceability score (0-10). The replaceability score indicates how well the summary "
        "captures the essential information: 0 means the summary captures everything needed and the "
        "full result can be safely discarded; 10 means the summary is insufficient and the full result "
        "must be read to understand the output.\n\n"
        "Output ONLY a JSON object with no extra text:\n"
        '{"summary": "<concise summary>", "score": <integer 0-10>}'
    )
    user_prompt = (
        f"Tool: {tool_name}\n"
        f"Arguments: {json.dumps(tool_input)}\n"
        f"Result:\n{truncated}"
    )

    try:
        response = await llm_client.chat.completions.create(
            model=config.llm.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            timeout=config.llm.timeout_ms / 1000.0,
        )
        content = response.choices[0].message.content.strip()
        parsed = json.loads(content)
        summary = parsed["summary"]
        score = int(parsed["score"])
        return summary, min(max(score, 0), 10)
    except Exception:
        logger.warning("Failed to summarize tool result for %s", tool_name, exc_info=True)
        fallback = truncated[:200] + ("..." if len(truncated) > 200 else "")
        return fallback, 10
