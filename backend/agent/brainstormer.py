import logging
from typing import Any, AsyncGenerator, Dict

from backend.agent.agent import Agent
from backend.graph.graph_store import GraphStore
from backend.i18n import t
from backend.llm.types import StreamChunk
from backend.graph.brainstormer import workflow

logger = logging.getLogger(__name__)


class Brainstormer(Agent):
    _graph: Any = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if Brainstormer._graph is None:
            Brainstormer._graph = workflow.compile(checkpointer=GraphStore.checkpointer)

    async def send(
        self,
        message: str,
        think_mode: bool,
        metadata: Dict[str, Any],
        sandbox: Any | None = None,
    ) -> AsyncGenerator[StreamChunk, None]:
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
            graph=Brainstormer._graph,
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
            graph=Brainstormer._graph,
            is_resume=True,
        ):
            yield chunk
