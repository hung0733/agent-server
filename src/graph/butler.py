"""Butler agent — processes IncomingMessage and returns a reply string.

Currently a stub that echoes the message back.
Replace the body of ``process()`` with a real LangGraph graph invocation.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from i18n import _

if TYPE_CHECKING:
    from channels.base import IncomingMessage

logger = logging.getLogger(__name__)


class Butler:
    """Agent that handles incoming messages from all channels.

    TODO: Replace process() stub with LangGraph graph.ainvoke().
    """

    async def process(self, msg: IncomingMessage) -> str:
        """Process an incoming message and return a reply.

        Args:
            msg: The IncomingMessage from any channel.

        Returns:
            Reply text to send back to the sender.
        """
        logger.info(
            _("Butler processing message id=%s from %s: %r"),
            msg.id,
            msg.sender_id,
            msg.text,
        )
        # Stub: echo back. Wire in LangGraph here.
        return f"收到你嘅訊息: {msg.text}"
