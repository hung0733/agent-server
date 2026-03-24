"""Unit tests for WhatsApp channel components."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from channels.base import ChannelType
from channels.whatsapp import WhatsAppChannel, WhatsAppWSClient
from msg_queue.dedup import MessageDeduplicator
from msg_queue.message_queue import MessageQueue


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_channel() -> WhatsAppChannel:
    return WhatsAppChannel(
        api_url="http://localhost:8080",
        api_key="test-key",
    )


def _make_ws_client(queue: MessageQueue, channel: WhatsAppChannel) -> WhatsAppWSClient:
    return WhatsAppWSClient(
        instance_name="test-instance",
        queue=queue,
        channel=channel,
        dedup=MessageDeduplicator(ttl_seconds=60),
        api_url="http://localhost:8080",
        api_key="test-key",
    )


# ---------------------------------------------------------------------------
# WhatsAppChannel — _clean_number
# ---------------------------------------------------------------------------

class TestCleanNumber:

    def test_strips_whatsapp_suffix(self):
        assert WhatsAppChannel._clean_number("85291234567@s.whatsapp.net") == "85291234567"

    def test_strips_group_suffix(self):
        assert WhatsAppChannel._clean_number("123456789@g.us") == "123456789"

    def test_plain_number_unchanged(self):
        assert WhatsAppChannel._clean_number("85291234567") == "85291234567"


# ---------------------------------------------------------------------------
# WhatsAppChannel — send_text
# ---------------------------------------------------------------------------

class TestSendText:

    async def test_send_text_posts_correct_payload(self):
        channel = _make_channel()
        mock_response = AsyncMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("channels.whatsapp.aiohttp.ClientSession", return_value=mock_session):
            await channel.send_text("my-instance", "85291234567", "Hello")

        mock_session.post.assert_called_once_with(
            "http://localhost:8080/message/sendText/my-instance",
            json={"number": "85291234567", "text": "Hello"},
            headers={"apikey": "test-key", "Content-Type": "application/json"},
        )

    async def test_send_text_logs_error_on_4xx(self, caplog):
        import logging
        channel = _make_channel()
        mock_response = AsyncMock()
        mock_response.status = 400
        mock_response.text = AsyncMock(return_value="Bad Request")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post.return_value = mock_response
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("channels.whatsapp.aiohttp.ClientSession", return_value=mock_session):
            with caplog.at_level(logging.ERROR, logger="channels.whatsapp"):
                await channel.send_text("inst", "123", "Hi")

        assert any("400" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# WhatsAppWSClient — _parse_event
# ---------------------------------------------------------------------------

def _upsert_payload(
    msg_id: str = "ABCDEF",
    remote_jid: str = "85291234567@s.whatsapp.net",
    from_me: bool = False,
    text: str = "你好",
) -> dict:
    return {
        "event": "messages.upsert",
        "data": {
            "key": {
                "id": msg_id,
                "remoteJid": remote_jid,
                "fromMe": from_me,
            },
            "message": {"conversation": text},
        },
    }


class TestParseEvent:

    def _client(self) -> WhatsAppWSClient:
        q = MessageQueue()
        ch = _make_channel()
        return _make_ws_client(q, ch)

    def test_valid_text_message(self):
        client = self._client()
        msg = client._parse_event(_upsert_payload())
        assert msg is not None
        assert msg.id == "ABCDEF"
        assert msg.sender_id == "85291234567"
        assert msg.text == "你好"
        assert msg.channel == ChannelType.whatsapp
        assert msg.instance_id == "test-instance"

    def test_drops_from_me(self):
        client = self._client()
        msg = client._parse_event(_upsert_payload(from_me=True))
        assert msg is None

    def test_drops_non_message_event(self):
        client = self._client()
        msg = client._parse_event({"event": "connection.update", "data": {}})
        assert msg is None

    def test_drops_missing_key_fields(self):
        client = self._client()
        msg = client._parse_event({"event": "messages.upsert", "data": {}})
        assert msg is None

    def test_uppercase_event_name(self):
        """Evolution API may send MESSAGES_UPSERT in some versions."""
        client = self._client()
        payload = _upsert_payload()
        payload["event"] = "MESSAGES_UPSERT"
        msg = client._parse_event(payload)
        assert msg is not None

    def test_extended_text_message(self):
        client = self._client()
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {"id": "X1", "remoteJid": "111@s.whatsapp.net", "fromMe": False},
                "message": {"extendedTextMessage": {"text": "延伸文字"}},
            },
        }
        msg = client._parse_event(payload)
        assert msg is not None
        assert msg.text == "延伸文字"

    def test_image_caption_extracted(self):
        client = self._client()
        payload = {
            "event": "messages.upsert",
            "data": {
                "key": {"id": "X2", "remoteJid": "222@s.whatsapp.net", "fromMe": False},
                "message": {"imageMessage": {"caption": "圖片說明"}},
            },
        }
        msg = client._parse_event(payload)
        assert msg is not None
        assert msg.text == "圖片說明"

    def test_callback_is_callable(self):
        client = self._client()
        msg = client._parse_event(_upsert_payload())
        assert msg is not None
        assert callable(msg.callback)


# ---------------------------------------------------------------------------
# WhatsAppWSClient — dedup integration
# ---------------------------------------------------------------------------

class TestWSClientDedup:

    async def test_duplicate_message_not_enqueued(self):
        q = MessageQueue()
        ch = _make_channel()
        client = _make_ws_client(q, ch)

        payload = _upsert_payload(msg_id="DUP-001")
        await client._handle_raw(payload)
        await client._handle_raw(payload)  # duplicate

        assert q.qsize() == 1

    async def test_distinct_messages_both_enqueued(self):
        q = MessageQueue()
        ch = _make_channel()
        client = _make_ws_client(q, ch)

        await client._handle_raw(_upsert_payload(msg_id="MSG-1", text="first"))
        await client._handle_raw(_upsert_payload(msg_id="MSG-2", text="second"))

        assert q.qsize() == 2
