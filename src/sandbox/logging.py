from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar
from uuid import uuid4


_operation_id_var: ContextVar[str | None] = ContextVar("sandbox_operation_id", default=None)


def current_operation_id() -> str | None:
    return _operation_id_var.get()


@asynccontextmanager
async def operation_context(operation_id: str | None = None):
    token = _operation_id_var.set(operation_id or uuid4().hex)
    try:
        yield _operation_id_var.get()
    finally:
        _operation_id_var.reset(token)
