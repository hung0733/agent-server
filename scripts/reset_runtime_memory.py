#!/usr/bin/env python3
"""Reset runtime memory, checkpoints, and vector records."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import quote_plus

import asyncpg
from dotenv import load_dotenv
from qdrant_client import AsyncQdrantClient, models

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.i18n import t
from backend.tdai_memory.manager import MemoryManager

PRESERVED_AGENT_FILES = {"SOUL.md", "IDENTITY.md"}
EMBEDDING_MODEL_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}
DEFAULT_VECTOR_DIMENSIONS = 1536


def _build_asyncpg_url() -> str:
    direct_url = os.getenv("TDAI_MEM_POSTGRES_URL") or os.getenv("DATABASE_URL")
    if direct_url:
        return direct_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = quote_plus(os.getenv("POSTGRES_PASSWORD", ""))
    database = os.getenv("POSTGRES_DB", "postgres")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def _quote_ident(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _status_row_count(status: str) -> int:
    parts = status.split()
    if parts and parts[-1].isdigit():
        return int(parts[-1])
    return 0


def collect_memory_file_targets(data_dir: str) -> list[Path]:
    root = Path(data_dir)
    if not root.exists():
        return []

    targets: list[Path] = []
    for agent_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        for child in sorted(agent_dir.iterdir()):
            if child.is_file() and child.name in PRESERVED_AGENT_FILES:
                continue
            targets.append(child)
    return targets


def reset_memory_files(data_dir: str, *, dry_run: bool) -> list[Path]:
    targets = collect_memory_file_targets(data_dir)
    if dry_run:
        return targets

    for path in targets:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    return targets


async def _discover_tables(conn, schema: str) -> list[str]:
    rows = await conn.fetch(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = $1
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """,
        schema,
    )
    return [row["table_name"] for row in rows]


async def _count_table(conn, schema: str, table: str, where_clause: str = "") -> int:
    qualified = f"{_quote_ident(schema)}.{_quote_ident(table)}"
    return await conn.fetchval(f"SELECT COUNT(*) FROM {qualified}{where_clause}")


async def _table_counts(conn, schema: str, tables: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in tables:
        counts[table] = await _count_table(conn, schema, table)
    return counts


async def _truncate_schema(conn, schema: str, tables: list[str]) -> None:
    if not tables:
        return
    qualified = ", ".join(
        f"{_quote_ident(schema)}.{_quote_ident(table)}" for table in tables
    )
    await conn.execute(f"TRUNCATE TABLE {qualified} RESTART IDENTITY CASCADE")


async def reset_postgres(*, dry_run: bool) -> dict[str, object]:
    memory_config = await MemoryManager.from_env()
    memory_schema = memory_config.postgres_schema
    langgraph_schema = os.getenv("LANGGRAPH_SCHEMA", "")
    if not langgraph_schema:
        raise RuntimeError(t("scripts.reset_runtime_memory.langgraph_schema_missing"))

    conn = await asyncpg.connect(_build_asyncpg_url())
    try:
        memory_tables = await _discover_tables(conn, memory_schema)
        langgraph_tables = await _discover_tables(conn, langgraph_schema)
        memory_table_counts = await _table_counts(conn, memory_schema, memory_tables)
        langgraph_table_counts = await _table_counts(
            conn,
            langgraph_schema,
            langgraph_tables,
        )
        agent_msg_hist_count = await _count_table(conn, "public", "agent_msg_hist")
        non_default_session_count = await _count_table(
            conn,
            "public",
            "session",
            " WHERE session_id NOT LIKE 'default-%'",
        )

        summary: dict[str, object] = {
            "memory_schema": memory_schema,
            "memory_tables": memory_tables,
            "memory_table_counts": memory_table_counts,
            "langgraph_schema": langgraph_schema,
            "langgraph_tables": langgraph_tables,
            "langgraph_table_counts": langgraph_table_counts,
            "agent_msg_hist_count": agent_msg_hist_count,
            "agent_msg_hist_deleted": 0,
            "non_default_session_count": non_default_session_count,
            "sessions_deleted": 0,
        }
        if dry_run:
            return summary

        async with conn.transaction():
            await _truncate_schema(conn, memory_schema, memory_tables)
            await _truncate_schema(conn, langgraph_schema, langgraph_tables)
            msg_status = await conn.execute("DELETE FROM public.agent_msg_hist")
            session_status = await conn.execute(
                "DELETE FROM public.session WHERE session_id NOT LIKE 'default-%'"
            )
            summary["agent_msg_hist_deleted"] = _status_row_count(msg_status)
            summary["sessions_deleted"] = _status_row_count(session_status)
        return summary
    finally:
        await conn.close()


async def _vector_dimensions() -> int:
    config = await MemoryManager.from_env()
    if config.embedding.dimensions > 0:
        return config.embedding.dimensions
    return EMBEDDING_MODEL_DIMENSIONS.get(
        config.embedding.model,
        DEFAULT_VECTOR_DIMENSIONS,
    )


async def reset_qdrant(*, dry_run: bool) -> dict[str, object]:
    config = await MemoryManager.from_env()
    collection_names = [
        config.qdrant_l0_collection,
        config.qdrant_l1_collection,
    ]
    client = AsyncQdrantClient(url=config.qdrant_url)
    try:
        collections = await client.get_collections()
        existing = {collection.name for collection in collections.collections}
        summary: dict[str, object] = {
            "url": config.qdrant_url,
            "collections": collection_names,
            "existing": [name for name in collection_names if name in existing],
            "missing": [name for name in collection_names if name not in existing],
        }
        if dry_run:
            return summary

        dimensions = await _vector_dimensions()
        for collection_name in collection_names:
            if collection_name in existing:
                await client.delete_collection(collection_name=collection_name)
            await client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=dimensions,
                    distance=models.Distance.COSINE,
                    on_disk=True,
                ),
            )
            await client.create_payload_index(
                collection_name=collection_name,
                field_name="agent_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        return summary
    finally:
        await client.close()


def _print_targets(label_key: str, values: list[object]) -> None:
    print(t(label_key) % len(values))
    for value in values:
        print(f"  - {value}")


def _print_table_counts(label_key: str, table_counts: dict[str, int]) -> None:
    print(t(label_key) % len(table_counts))
    for table, count in table_counts.items():
        print(f"  - {table}: {count}")


async def run(*, yes: bool) -> None:
    dry_run = not yes
    config = await MemoryManager.from_env()

    mode_key = (
        "scripts.reset_runtime_memory.dry_run"
        if dry_run
        else "scripts.reset_runtime_memory.apply"
    )
    print(t(mode_key))
    print(t("scripts.reset_runtime_memory.warning"))

    file_targets = reset_memory_files(config.data_dir, dry_run=dry_run)
    print(t("scripts.reset_runtime_memory.data_dir") % config.data_dir)
    _print_targets("scripts.reset_runtime_memory.file_targets", file_targets)

    postgres_summary = await reset_postgres(dry_run=dry_run)
    print(
        t("scripts.reset_runtime_memory.postgres_memory_schema")
        % postgres_summary["memory_schema"]
    )
    _print_table_counts(
        "scripts.reset_runtime_memory.table_targets",
        postgres_summary["memory_table_counts"],
    )
    print(
        t("scripts.reset_runtime_memory.postgres_langgraph_schema")
        % postgres_summary["langgraph_schema"]
    )
    _print_table_counts(
        "scripts.reset_runtime_memory.table_targets",
        postgres_summary["langgraph_table_counts"],
    )
    print(
        t("scripts.reset_runtime_memory.public_agent_msg_hist")
        % postgres_summary["agent_msg_hist_count"]
    )
    print(
        t("scripts.reset_runtime_memory.public_session")
        % postgres_summary["non_default_session_count"]
    )

    qdrant_summary = await reset_qdrant(dry_run=dry_run)
    print(t("scripts.reset_runtime_memory.qdrant_url") % qdrant_summary["url"])
    _print_targets(
        "scripts.reset_runtime_memory.qdrant_existing",
        qdrant_summary["existing"],
    )
    _print_targets(
        "scripts.reset_runtime_memory.qdrant_missing",
        qdrant_summary["missing"],
    )

    print(t("scripts.reset_runtime_memory.completed"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=t("scripts.reset_runtime_memory.description"),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=t("scripts.reset_runtime_memory.yes_help"),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    asyncio.run(run(yes=args.yes))


if __name__ == "__main__":
    main()
