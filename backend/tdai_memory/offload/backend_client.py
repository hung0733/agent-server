from __future__ import annotations

import json
import logging

import httpx
import openai

logger = logging.getLogger(__name__)

_SUMMARIZE_PROMPT = (
    "You are a tool result summarizer. Given a list of tool call/result pairs, produce concise summaries "
    "for each pair. Output ONLY a JSON array of objects, each with keys:\n"
    '  - "tool_call_id": the original tool_call_id\n'
    '  - "summary": concise summary of the tool call and its result\n'
    "Return exactly one object per input pair, in the same order."
)

_JUDGE_L15_PROMPT = (
    "You are a task boundary detector. Given a chronological list of tool execution summaries, "
    "identify boundaries where a new sub-task or phase begins. "
    "Output ONLY a JSON object:\n"
    '  - "boundaries": list of tool_call_ids that start a new sub-task\n'
    '  - "labels": dict mapping each boundary tool_call_id to a short sub-task label\n'
    "If no clear boundaries exist, return empty lists."
)

_GENERATE_L2_PROMPT = (
    "You generate Mermaid flowcharts from tool execution logs. "
    "Output ONLY a Mermaid flowchart in ```mermaid ... ``` format. "
    "Use `flowchart TD`. Node IDs must follow `N1`, `N2`, ... pattern. "
    "Include tool summaries as node labels with `<br/>` for line breaks. "
    "Group related actions into subgraphs."
)

_GENERATE_L4_PROMPT = (
    "You generate reusable skill definitions from tool execution logs. "
    "Output ONLY a JSON object with keys:\n"
    '  - "skills": list of skill objects with "name", "description", "steps" fields\n'
    '  - "summary": overall summary of the execution pattern\n'
    "Each skill step should describe the tool call and expected outcome."
)


class BackendClient:
    def __init__(self, url: str | None = None, api_key: str = "", timeout_ms: int = 120000) -> None:
        self._url = url
        self._api_key = api_key
        self._timeout = timeout_ms / 1000.0
        self._client: openai.AsyncOpenAI | None = None

    async def is_available(self) -> bool:
        if not self._url:
            return False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._url}/health")
                return resp.status_code == 200
        except Exception:
            logger.debug("Backend health check failed", exc_info=True)
            return False

    def _get_llm_client(self) -> openai.AsyncOpenAI:
        if self._client is None:
            if self._url:
                self._client = openai.AsyncOpenAI(
                    base_url=f"{self._url}/v1",
                    api_key=self._api_key,
                    timeout=self._timeout,
                )
            else:
                self._client = openai.AsyncOpenAI(
                    api_key=self._api_key,
                    timeout=self._timeout,
                )
        return self._client

    async def summarize(self, tool_pairs: list[dict], model: str) -> list[dict]:
        llm = self._get_llm_client()
        user_content = json.dumps(tool_pairs, ensure_ascii=False)
        try:
            response = await llm.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SUMMARIZE_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                timeout=self._timeout,
            )
            content = response.choices[0].message.content.strip()
            return json.loads(content)
        except Exception:
            logger.warning("Backend summarize failed", exc_info=True)
            return []

    async def judge_l15(self, entries: list[dict], model: str) -> dict:
        llm = self._get_llm_client()
        user_content = json.dumps(entries, ensure_ascii=False)
        try:
            response = await llm.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _JUDGE_L15_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                timeout=self._timeout,
            )
            content = response.choices[0].message.content.strip()
            return json.loads(content)
        except Exception:
            logger.warning("Backend judge_l15 failed", exc_info=True)
            return {"boundaries": [], "labels": {}}

    async def generate_l2(self, entries: list[dict], model: str) -> dict:
        llm = self._get_llm_client()
        user_content = json.dumps(entries, ensure_ascii=False)
        try:
            response = await llm.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _GENERATE_L2_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                timeout=self._timeout,
            )
            content = response.choices[0].message.content.strip()
            if "```mermaid" in content:
                start = content.index("```mermaid") + len("```mermaid")
                end = content.index("```", start)
                mmd = content[start:end].strip()
            elif "```" in content:
                start = content.index("```") + 3
                end = content.index("```", start)
                mmd = content[start:end].strip()
                if mmd.startswith("mermaid"):
                    mmd = mmd[len("mermaid"):].strip()
            else:
                mmd = content
            return {"mermaid": mmd.strip()}
        except Exception:
            logger.warning("Backend generate_l2 failed", exc_info=True)
            return {"mermaid": ""}

    async def generate_l4(self, entries: list[dict], model: str, focus: str = "") -> dict:
        llm = self._get_llm_client()
        user_content = json.dumps(entries, ensure_ascii=False)
        if focus:
            user_content = f"Focus area: {focus}\n\n{user_content}"
        try:
            response = await llm.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _GENERATE_L4_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.0,
                timeout=self._timeout,
            )
            content = response.choices[0].message.content.strip()
            return json.loads(content)
        except Exception:
            logger.warning("Backend generate_l4 failed", exc_info=True)
            return {"skills": [], "summary": ""}
