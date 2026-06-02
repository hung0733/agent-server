from __future__ import annotations

import pytest

from backend.channels.types import WhatsAppInboundMessage
from scripts import test_whatsapp_commands as smoke_script


class FakeWhatsAppChannel:
    instances = []

    def __init__(
        self,
        *,
        whatsapp_instance,
        whatsapp_key,
        api_url=None,
        global_api_key=None,
    ):
        self.whatsapp_instance = whatsapp_instance
        self.whatsapp_key = whatsapp_key
        self.api_url = api_url
        self.global_api_key = global_api_key
        self.calls = []
        self.closed = False
        type(self).instances.append(self)

    async def ensure_message_listener_enabled(self):
        self.calls.append(("ensure_message_listener_enabled",))
        return {"ok": True}

    async def send_text(self, number, text):
        self.calls.append(("send_text", number, text))
        return {"key": {"id": "sent-msg-1"}}

    async def send_media(self, number, mediatype, media, **options):
        self.calls.append(("send_media", number, mediatype, media, options))
        return {"key": {"id": "media-msg-1"}}

    async def find_latest_outbound_message_id(self, remote_jid):
        self.calls.append(("find_latest_outbound_message_id", remote_jid))
        return "latest-msg-1"

    async def mark_message_as_read(self, number, message_id):
        self.calls.append(("mark_message_as_read", number, message_id))
        return {"ok": True}

    def listen_messages(self):
        self.calls.append(("listen_messages",))
        return self._listen_messages()

    async def _listen_messages(self):
        yield WhatsAppInboundMessage(
            event="messages.upsert",
            instance=self.whatsapp_instance,
            data={"key": {"id": "inbound-msg-1"}},
            raw={"event": "messages.upsert"},
        )

    async def close(self):
        self.calls.append(("close",))
        self.closed = True


@pytest.fixture(autouse=True)
def reset_fake_channel(monkeypatch):
    FakeWhatsAppChannel.instances = []
    monkeypatch.delenv("WHATSAPP_INSTANCE", raising=False)
    monkeypatch.delenv("WHATSAPP_KEY", raising=False)
    monkeypatch.delenv("EVOLUTION_API_KEY", raising=False)


@pytest.mark.asyncio
async def test_run_smoke_test_calls_all_whatsapp_commands():
    options = smoke_script.WhatsAppCommandSmokeOptions(
        instance="Moss",
        key="instance-key",
        number="85298765432",
        media_url="https://example.test/image.jpg",
        media_type="image",
        media_caption="caption",
        listen_seconds=0.1,
        api_url="http://evolution.test",
        global_api_key="global-key",
    )

    exit_code = await smoke_script.run_smoke_test(
        options,
        channel_factory=FakeWhatsAppChannel,
    )

    assert exit_code == 0
    channel = FakeWhatsAppChannel.instances[0]
    assert channel.whatsapp_instance == "Moss"
    assert channel.whatsapp_key == "instance-key"
    assert channel.api_url == "http://evolution.test"
    assert channel.global_api_key == "global-key"
    assert channel.calls == [
        ("ensure_message_listener_enabled",),
        (
            "send_text",
            "85298765432",
            "agent-server WhatsApp command smoke test",
        ),
        (
            "send_media",
            "85298765432",
            "image",
            "https://example.test/image.jpg",
            {"caption": "caption"},
        ),
        (
            "find_latest_outbound_message_id",
            "85298765432@s.whatsapp.net",
        ),
        ("mark_message_as_read", "85298765432", "sent-msg-1"),
        ("listen_messages",),
        ("close",),
    ]
    assert channel.closed is True


@pytest.mark.asyncio
async def test_run_smoke_test_requires_instance_and_key():
    options = smoke_script.WhatsAppCommandSmokeOptions()

    exit_code = await smoke_script.run_smoke_test(
        options,
        channel_factory=FakeWhatsAppChannel,
    )

    assert exit_code == 1
    assert FakeWhatsAppChannel.instances == []
