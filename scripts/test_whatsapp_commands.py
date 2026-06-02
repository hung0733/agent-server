#!/usr/bin/env python3
"""Smoke test Evolution WhatsApp commands used by the runtime.

Usage:
    python -m scripts.test_whatsapp_commands --instance Moss --number 85298765432
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.channels import EvolutionWhatsAppChannel
from backend.i18n import t

DEFAULT_MEDIA_TYPE = "image"

logger = logging.getLogger(__name__)


@dataclass
class WhatsAppCommandSmokeOptions:
    instance: str | None = None
    key: str | None = None
    number: str | None = None
    remote_jid: str | None = None
    message_id: str | None = None
    media_url: str | None = None
    media_type: str = DEFAULT_MEDIA_TYPE
    media_caption: str | None = None
    listen_seconds: float = 0.0
    api_url: str | None = None
    global_api_key: str | None = None


def _print_step(message_key: str, *args: Any) -> None:
    print(t(message_key) % args if args else t(message_key))


async def _run_step(name: str, action: Callable[[], Any]) -> Any:
    _print_step("scripts.test_agent_sandbox.step_start", name)
    result = action()
    if hasattr(result, "__await__"):
        result = await result
    _print_step("scripts.test_agent_sandbox.step_ok", name)
    return result


def _remote_jid_from_number(number: str | None) -> str | None:
    if not number:
        return None
    if "@" in number:
        return number
    return f"{number}@s.whatsapp.net"


def _extract_message_id(response: dict[str, Any] | None) -> str | None:
    if not isinstance(response, dict):
        return None
    key = response.get("key")
    if isinstance(key, dict) and isinstance(key.get("id"), str):
        return key["id"]
    for field in ("messageId", "id"):
        value = response.get(field)
        if isinstance(value, str):
            return value
    return None


async def _probe_listener(
    channel: EvolutionWhatsAppChannel, listen_seconds: float
) -> Any:
    listener = channel.listen_messages()
    task = asyncio.create_task(anext(listener))
    try:
        message = await asyncio.wait_for(task, timeout=listen_seconds)
        return message.raw
    except TimeoutError:
        _print_step("scripts.test_whatsapp_commands.listener_timeout", listen_seconds)
        return None
    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, StopAsyncIteration):
            pass
        await listener.aclose()


async def run_smoke_test(
    options: WhatsAppCommandSmokeOptions,
    *,
    channel_factory: Callable[..., EvolutionWhatsAppChannel] = EvolutionWhatsAppChannel,
) -> int:
    load_dotenv()
    instance = options.instance or os.getenv("WHATSAPP_INSTANCE")
    key = options.key or os.getenv("WHATSAPP_KEY") or os.getenv("EVOLUTION_API_KEY")

    if not instance:
        print(t("scripts.test_whatsapp_commands.missing_instance"))
        return 1
    if not key:
        print(t("scripts.test_whatsapp_commands.missing_key"))
        return 1

    channel = channel_factory(
        whatsapp_instance=instance,
        whatsapp_key=key,
        api_url=options.api_url,
        global_api_key=options.global_api_key,
    )

    try:
        _print_step("scripts.test_whatsapp_commands.start", instance)
        await _run_step("websocket/set", channel.ensure_message_listener_enabled)

        sent_message_id: str | None = None
        if options.number:
            response = await _run_step(
                "message/sendText",
                lambda: channel.send_text(
                    options.number,
                    t("scripts.test_whatsapp_commands.default_text"),
                ),
            )
            sent_message_id = _extract_message_id(response)
            if sent_message_id:
                _print_step(
                    "scripts.test_whatsapp_commands.sent_message_id", sent_message_id
                )
        else:
            _print_step(
                "scripts.test_whatsapp_commands.skipped",
                "message/sendText",
                "number",
            )

        if options.media_url:
            if not options.number:
                raise ValueError(
                    t("scripts.test_whatsapp_commands.missing_number_for_media")
                )
            await _run_step(
                "message/sendMedia",
                lambda: channel.send_media(
                    options.number,
                    options.media_type,
                    options.media_url,
                    caption=options.media_caption,
                ),
            )
        else:
            _print_step(
                "scripts.test_whatsapp_commands.skipped",
                "message/sendMedia",
                "media-url",
            )

        remote_jid = (
            options.remote_jid
            or _remote_jid_from_number(options.number)
            or os.getenv("WHATSAPP_TEST_REMOTE_JID")
        )
        latest_message_id: str | None = None
        if remote_jid:
            latest_message_id = await _run_step(
                "chat/findMessages",
                lambda: channel.find_latest_outbound_message_id(remote_jid),
            )
            if latest_message_id:
                _print_step(
                    "scripts.test_whatsapp_commands.latest_message_id",
                    latest_message_id,
                )
        else:
            _print_step(
                "scripts.test_whatsapp_commands.skipped",
                "chat/findMessages",
                "remote-jid",
            )

        read_message_id = options.message_id or sent_message_id or latest_message_id
        if options.number and read_message_id:
            await _run_step(
                "chat/markMessageAsRead",
                lambda: channel.mark_message_as_read(options.number, read_message_id),
            )
        else:
            _print_step(
                "scripts.test_whatsapp_commands.skipped",
                "chat/markMessageAsRead",
                "number/message-id",
            )

        if options.listen_seconds > 0:
            await _run_step(
                "socket.io listen_messages",
                lambda: _probe_listener(channel, options.listen_seconds),
            )
        else:
            _print_step(
                "scripts.test_whatsapp_commands.skipped",
                "socket.io listen_messages",
                "listen-seconds",
            )

        _print_step("scripts.test_whatsapp_commands.success")
        return 0
    except Exception as exc:
        logger.exception("%s: %s", t("scripts.test_whatsapp_commands.failed"), exc)
        print(f"{t('scripts.test_whatsapp_commands.failed')}: {exc}")
        return 1
    finally:
        await channel.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=t("scripts.test_whatsapp_commands.description")
    )
    parser.add_argument(
        "--instance", help=t("scripts.test_whatsapp_commands.instance_help")
    )
    parser.add_argument("--key", help=t("scripts.test_whatsapp_commands.key_help"))
    parser.add_argument("--number", help=t("scripts.test_whatsapp_commands.number_help"))
    parser.add_argument(
        "--remote-jid", help=t("scripts.test_whatsapp_commands.remote_jid_help")
    )
    parser.add_argument(
        "--message-id", help=t("scripts.test_whatsapp_commands.message_id_help")
    )
    parser.add_argument(
        "--media-url", help=t("scripts.test_whatsapp_commands.media_url_help")
    )
    parser.add_argument(
        "--media-type",
        default=DEFAULT_MEDIA_TYPE,
        choices=["image", "video", "audio", "document"],
        help=t("scripts.test_whatsapp_commands.media_type_help"),
    )
    parser.add_argument(
        "--media-caption", help=t("scripts.test_whatsapp_commands.media_caption_help")
    )
    parser.add_argument(
        "--listen-seconds",
        type=float,
        default=0.0,
        help=t("scripts.test_whatsapp_commands.listen_seconds_help"),
    )
    parser.add_argument(
        "--api-url", help=t("scripts.test_whatsapp_commands.api_url_help")
    )
    parser.add_argument(
        "--global-api-key",
        help=t("scripts.test_whatsapp_commands.global_api_key_help"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = _build_parser().parse_args(argv)
    options = WhatsAppCommandSmokeOptions(**vars(args))
    return asyncio.run(run_smoke_test(options))


if __name__ == "__main__":
    raise SystemExit(main())
