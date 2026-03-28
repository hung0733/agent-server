"""Dashboard API key authentication helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from db.dao.api_key_dao import APIKeyDAO
from db.dao.user_dao import UserDAO


def hash_api_key(raw_key: str) -> str:
    return f"sha256:{hashlib.sha256(raw_key.encode('utf-8')).hexdigest()}"


@dataclass(slots=True)
class DashboardAuthService:
    """Authenticate dashboard requests with user API keys."""

    async def authenticate(self, raw_key: str) -> dict[str, Any] | None:
        key_hash = hash_api_key(raw_key)
        api_key = await APIKeyDAO.get_by_key_hash(key_hash)
        if api_key is None or not api_key.is_active:
            return None

        if api_key.expires_at is not None:
            expires_at = api_key.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at.astimezone(UTC) <= datetime.now(UTC):
                return None

        user = await UserDAO.get_by_id(api_key.user_id)
        if user is None or not user.is_active:
            return None

        return {
            "user_id": api_key.user_id,
            "api_key_id": api_key.id,
        }
