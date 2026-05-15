from __future__ import annotations

import base64
import binascii
import mimetypes
from typing import Any

import httpx

from backend.channels.types import ReceivedMessage
from backend.queues.message_queue import FilePayload


async def build_evolution_files(
    message: ReceivedMessage,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> list[FilePayload] | None:
    if not message.has_media or not message.media_url:
        return None

    file_bytes = await _read_media_bytes(message.media_url, http_client=http_client)
    return [
        {
            "mimetype": message.media_mimetype,
            "filename": message.file_name or _default_filename(message),
            "bytes": file_bytes,
        }
    ]


async def _read_media_bytes(media: str, *, http_client: httpx.AsyncClient | None = None) -> bytes:
    if media.startswith("http://") or media.startswith("https://"):
        if http_client:
            response = await http_client.get(media)
            response.raise_for_status()
            return response.content

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(media)
            response.raise_for_status()
            return response.content

    return _decode_base64(media)


def _decode_base64(media: str) -> bytes:
    if "," in media and media.split(",", 1)[0].startswith("data:"):
        media = media.split(",", 1)[1]
    try:
        return base64.b64decode(media, validate=True)
    except binascii.Error:
        return media.encode()


def _default_filename(message: ReceivedMessage) -> str:
    extension = mimetypes.guess_extension(message.media_mimetype or "") or ""
    stem = message.message_id or message.content_type or "file"
    return f"{stem}{extension}"
