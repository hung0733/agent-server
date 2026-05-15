from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any

from backend.channels.types import InteractiveButton, InteractiveListSection, MediaType, WhatsAppInboundMessage


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
    async def send_interactive_buttons(
        self,
        number: str,
        title: str,
        buttons: Sequence[InteractiveButton],
        **options: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def send_interactive_list(
        self,
        number: str,
        title: str,
        button_text: str,
        footer_text: str,
        sections: Sequence[InteractiveListSection],
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
