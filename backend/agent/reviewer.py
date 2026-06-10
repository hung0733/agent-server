import logging
from typing import Any, AsyncGenerator, Dict

from backend.agent.agent import Agent
from backend.graph.graph_store import GraphStore
from backend.graph.reviewer import workflow
from backend.i18n import t
from backend.llm.types import StreamChunk

logger = logging.getLogger(__name__)


class Reviewer(Agent):
    _graph: Any = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if Reviewer._graph is None:
            Reviewer._graph = workflow.compile(checkpointer=GraphStore.checkpointer)

    async def send(
        self,
        message: str,
        think_mode: bool,
        metadata: Dict[str, Any],
        sandbox: Any | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
        message += """

現在開始輸出Json結構。
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
            graph=Reviewer._graph,
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
            graph=Reviewer._graph,
            is_resume=True,
        ):
            yield chunk
