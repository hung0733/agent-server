import logging
from typing import Any, AsyncGenerator, Dict

from backend.agent.agent import Agent
from backend.graph.graph_store import GraphStore
from backend.graph.planner import workflow
from backend.i18n import t
from backend.llm.types import StreamChunk

logger = logging.getLogger(__name__)


class Planner(Agent):
    _graph: Any = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if Planner._graph is None:
            Planner._graph = workflow.compile(checkpointer=GraphStore.checkpointer)

    async def send(
        self,
        message: str,
        think_mode: bool,
        metadata: Dict[str, Any],
        sandbox: Any | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:

        message += """

## 輸出格式規範 (JSON Output Constraints)
- 最終答案必須只係一個純 JSON array：`[...]`。
- 不得輸出 Markdown code fence、HTML、自然語言總結、註解、前言、後記或 `{ "steps": [...] }` wrapper。
- 每個 array item 必須只包含以下欄位：`agent_type`、`title`、`goal`、`dependsOn`、`status`、`seq_no`。
- `agent_type` 只可用：`engineer`、`researcher`、`writer`、`reviewer`。
- `title` 要短、清楚、唯一。
- `goal` 必須非常詳細，令後續 agent 只讀該 step 都做到目標效果。
- `dependsOn` 只可係 `null` 或一個整數；不可用 array、不可用 title、不可放多個依賴。
- `dependsOn` 整數必須引用已存在、而且較小的 `seq_no`。
- 無前置依賴用 `null`。
- 如一個 step 需要多個前置條件，必須先建立一個整合或驗收 step，後續 step 只依賴該整合或驗收 step 的 `seq_no`。
- `status` 只可用大階：`PENDING` 或 `BLOCKED`。
- 通常只有無依賴或當前可即時開始的第一批 step 用 `PENDING`；有前置依賴的 step 用 `BLOCKED`。
- `seq_no` 必須由 4 開始，按建議執行順序遞增。
- 每個 step 必須符合以下形態：

```json
{
  "agent_type": "engineer",
  "title": "A1",
  "goal": "非常詳細的執行指令",
  "dependsOn": null,
  "status": "PENDING",
  "seq_no": 1
}
```
"""

        logger.info(
            t("agent.send_started"),
            self.session_id,
            len(message),
            think_mode,
        )
        async for chunk in Agent.proc_send_and_resume(
            agent=self,
            message=message,
            think_mode=think_mode,
            metadata=metadata,
            sandbox=sandbox,
            graph=Planner._graph,
        ):
            yield chunk

    async def resume(
        self,
        message: str,
        think_mode: bool,
        metadata: Dict[str, Any],
        sandbox: Any | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        logger.info(
            t("agent.resume_started"),
            self.session_id,
            len(message),
            think_mode,
        )
        async for chunk in Agent.proc_send_and_resume(
            agent=self,
            message=message,
            think_mode=think_mode,
            metadata=metadata,
            sandbox=sandbox,
            graph=Planner._graph,
            is_resume=True,
        ):
            yield chunk
