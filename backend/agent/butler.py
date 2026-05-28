import logging
from typing import Any, AsyncGenerator, Dict

from backend.agent.agent import Agent
from backend.graph.graph_store import GraphStore
from backend.i18n import t
from backend.llm.types import StreamChunk
from backend.graph.bulter import workflow

logger = logging.getLogger(__name__)


class Bulter(Agent):
    _graph: Any = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if Bulter._graph is None:
            Bulter._graph = workflow.compile(checkpointer=GraphStore.checkpointer)

    async def send(
        self,
        message: str,
        think_mode: bool,
        metadata: Dict[str, Any],
    ) -> AsyncGenerator[StreamChunk, None]:
        logger.info(
            t("agent.send_started"),
            self.session_id,
            len(message),
            think_mode,
        )
        async for chunk in Agent.proc_send(
            agent=self,
            message=message,
            think_mode=think_mode,
            metadata=metadata,
            graph=Bulter._graph,
        ):
            yield chunk
