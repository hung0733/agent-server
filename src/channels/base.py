"""Base types for all communication channels."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Awaitable, Callable, Optional


class ChannelType(StrEnum):
    whatsapp = "whatsapp"


@dataclass
class IncomingMessage:
    """Represents a message received from any channel.

    Attributes:
        id:          Channel-native message ID (used for dedup).
        channel:     Source channel type.
        instance_id: Channel instance / connection name.
        sender_id:   Phone number or user ID of the sender.
        text:        Plain-text content (empty string if media-only).
        media_url:   Optional URL for media attachment.
        priority:    Queue priority — higher = processed first.
                     2=critical, 1=high, 0=normal (default), -1=low.
        received_at: UTC timestamp when the message was received.
        callback:    Async callable to send a reply back to the sender.
    """

    id: str
    channel: ChannelType
    instance_id: str
    sender_id: str
    receiver_id: str
    text: str
    media_url: Optional[str] = None
    priority: int = 0
    received_at: datetime = field(default_factory=datetime.utcnow)
    callback: Callable[[str], Awaitable[None]] = field(repr=False, default=None)  # type: ignore[assignment]

    def __lt__(self, other: object) -> bool:
        """Required by asyncio.PriorityQueue when priorities are equal."""
        if not isinstance(other, IncomingMessage):
            return NotImplemented
        return self.received_at < other.received_at


class AbstractChannel(ABC):
    """Abstract base for all outbound channel implementations."""

    @abstractmethod
    async def send_text(
        self, instance_id: str, recipient_id: str, text: str
    ) -> None:
        """Send a plain-text reply to a recipient.

        Args:
            instance_id:  Channel instance / connection name.
            recipient_id: Phone number or user ID of the recipient.
            text:         Message content to send.
        """
