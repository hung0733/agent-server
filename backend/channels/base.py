from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from backend.channels.types import MediaType, WhatsAppInboundMessage


class CommunicationChannel(ABC):
    @abstractmethod
    async def send_text(self, number: str, text: str, **options: Any) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def send_media(
        self,
        number: str,
        mediatype: MediaType,
        media: str,
        **options: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def mark_message_as_read(self, number: str, message_id: str) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def listen_messages(self) -> AsyncIterator[WhatsAppInboundMessage]:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError
