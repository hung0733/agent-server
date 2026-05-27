from __future__ import annotations

import os
import re
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg
import pytest_asyncio
from dotenv import load_dotenv


_TEST_MEMORY_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TEST_MEMORY_SCHEMA_PREFIX = "test_memories_"
_TEST_MEMORY_SCHEMA_BASE = "test_memories"


def make_tdai_memory_test_schema(base_schema: str | None = None) -> str:
    if base_schema is None:
        load_dotenv()
        base_schema = (
            os.getenv("TDAI_MEM_POSTGRES_TEST_SCHEMA") or _TEST_MEMORY_SCHEMA_BASE
        )

    return f"{base_schema}_{os.getpid()}_{uuid.uuid4().hex[:8]}"


def is_safe_tdai_memory_test_schema(schema: str) -> bool:
    return (
        bool(_TEST_MEMORY_SCHEMA_RE.fullmatch(schema))
        and schema.startswith(_TEST_MEMORY_SCHEMA_PREFIX)
        and len(schema) > len(_TEST_MEMORY_SCHEMA_PREFIX)
        and schema != _TEST_MEMORY_SCHEMA_BASE
    )


def require_safe_tdai_memory_test_schema(schema: str) -> None:
    if not is_safe_tdai_memory_test_schema(schema):
        raise ValueError("unsafe TDAI memory test schema")


def get_tdai_memory_postgres_url() -> str:
    load_dotenv()
    url = os.getenv("TDAI_MEM_POSTGRES_URL") or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("TDAI memory PostgreSQL URL is not configured")
    return url


async def create_tdai_memory_test_schema(schema: str, postgres_url: str) -> None:
    require_safe_tdai_memory_test_schema(schema)
    conn = await asyncpg.connect(postgres_url)
    try:
        await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    finally:
        await conn.close()


async def drop_tdai_memory_test_schema(schema: str, postgres_url: str) -> None:
    require_safe_tdai_memory_test_schema(schema)
    conn = await asyncpg.connect(postgres_url)
    try:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        await conn.close()


@asynccontextmanager
async def tdai_memory_test_schema_context(
    base_schema: str | None = None,
    postgres_url: str | None = None,
) -> AsyncIterator[str]:
    schema = make_tdai_memory_test_schema(base_schema)
    url = postgres_url or get_tdai_memory_postgres_url()

    await create_tdai_memory_test_schema(schema, url)
    try:
        yield schema
    finally:
        await drop_tdai_memory_test_schema(schema, url)


@pytest_asyncio.fixture
async def tdai_memory_test_schema() -> AsyncIterator[str]:
    async with tdai_memory_test_schema_context() as schema:
        yield schema
