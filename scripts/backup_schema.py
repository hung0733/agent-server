#!/usr/bin/env python3
"""
Database Schema Backup Script

Generates a schema-only backup of the current database state by querying
information_schema and exporting table definitions as CREATE TABLE statements.

Usage:
    python backup_schema.py > backup_pre_migration_{timestamp}.sql
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv
from sqlalchemy import MetaData, Table, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_engine_from_config
from sqlalchemy.pool import NullPool


# Add src to sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def _build_dsn() -> str:
    """Build PostgreSQL DSN from environment variables.
    
    Returns:
        PostgreSQL DSN string in format:
        postgresql+asyncpg://user:password@host:port/database
        
    Raises:
        RuntimeError: If any required environment variable is missing
    """
    load_dotenv()
    
    def _validate_env_var(name: str) -> str:
        value = os.getenv(name)
        if value is None:
            raise RuntimeError(f"Required environment variable '{name}' is not set")
        return value
    
    host = _validate_env_var("POSTGRES_HOST")
    port = _validate_env_var("POSTGRES_PORT")
    user = _validate_env_var("POSTGRES_USER")
    password = _validate_env_var("POSTGRES_PASSWORD")
    database = _validate_env_var("POSTGRES_DB")
    
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


async def get_table_columns(engine: AsyncEngine, table_name: str, schema: str = "public") -> List[Tuple]:
    """Query information_schema to get column details for a table."""
    async with engine.connect() as conn:
        query = text("""
            SELECT 
                column_name,
                data_type,
                character_maximum_length,
                numeric_precision,
                numeric_scale,
                is_nullable,
                column_default
            FROM information_schema.columns
            WHERE table_schema = :schema
              AND table_name = :table_name
            ORDER BY ordinal_position
        """)
        result = await conn.execute(query, {"schema": schema, "table_name": table_name})
        return result.fetchall()


async def get_table_constraints(engine: AsyncEngine, table_name: str, schema: str = "public") -> List[str]:
    """Query information_schema to get constraints for a table."""
    async with engine.connect() as conn:
        query = text("""
            SELECT 
                con.conname as constraint_name,
                pg_get_constraintdef(con.oid) as constraint_def
            FROM pg_constraint con
            JOIN pg_class cls ON con.conrelid = cls.oid
            JOIN pg_namespace nsp ON cls.relnamespace = nsp.oid
            WHERE nsp.nspname = :schema
              AND cls.relname = :table_name
            ORDER BY con.contype DESC, con.conname
        """)
        result = await conn.execute(query, {"schema": schema, "table_name": table_name})
        rows = result.fetchall()
        return [f"CONSTRAINT {row[0]} {row[1]}" for row in rows]


async def get_all_tables(engine: AsyncEngine, schema: str = "public") -> List[str]:
    """Get list of all tables in the schema."""
    async with engine.connect() as conn:
        query = text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = :schema
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        result = await conn.execute(query, {"schema": schema})
        return [row[0] for row in result.fetchall()]


async def get_alembic_version(engine: AsyncEngine) -> List[str]:
    """Get current migration version from alembic_version table."""
    async with engine.connect() as conn:
        try:
            query = text("SELECT version_num FROM alembic_version ORDER BY version_num DESC")
            result = await conn.execute(query)
            rows = result.fetchall()
            return [row[0] for row in rows]
        except Exception:
            return []


async def generate_create_table_sql(engine: AsyncEngine, table_name: str, schema: str = "public") -> str:
    """Generate CREATE TABLE statement for a given table."""
    columns = await get_table_columns(engine, table_name, schema)
    constraints = await get_table_constraints(engine, table_name, schema)
    
    lines = []
    for col in columns:
        col_name, data_type, char_max_len, num_precision, num_scale, is_nullable, col_default = col
        
        # Build column definition
        col_def = f"    {col_name} {data_type}"
        
        # Add length for character types
        if data_type in ('character varying', 'character') and char_max_len is not None:
            col_def += f"({char_max_len})"
        elif data_type == 'USER-DEFINED':
            # Could be enum or other custom type - skip details for now
            pass
        
        # Add precision/scale for numeric types
        if data_type in ('numeric', 'decimal') and num_precision is not None:
            if num_scale is not None and num_scale > 0:
                col_def += f"({num_precision},{num_scale})"
            else:
                col_def += f"({num_precision})"
        
        # Add NOT NULL constraint
        if is_nullable == 'NO':
            col_def += " NOT NULL"
        
        # Add DEFAULT
        if col_default is not None:
            col_def += f" DEFAULT {col_default}"
        
        lines.append(col_def)
    
    # Add table constraints
    for constraint in constraints:
        lines.append(f"    {constraint}")
    
    # Build CREATE TABLE statement
    create_sql = f"CREATE TABLE {schema}.{table_name} (\n"
    create_sql += ",\n".join(lines)
    create_sql += "\n);"
    
    return create_sql


async def generate_schema_backup() -> str:
    """Generate complete schema backup."""
    dsn = _build_dsn()
    
    config = {
        "sqlalchemy.url": dsn,
    }
    
    engine = async_engine_from_config(config, prefix="sqlalchemy.", poolclass=NullPool)
    
    try:
        output_lines = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        output_lines.append(f"-- Database Schema Backup")
        output_lines.append(f"-- Generated: {timestamp}")
        output_lines.append(f"-- Database: {dsn.split('@')[-1]}")
        output_lines.append("")
        
        # Get and document migration status
        versions = await get_alembic_version(engine)
        output_lines.append("-- Migration Status (alembic_version)")
        if versions:
            for version in versions:
                output_lines.append(f"-- Version: {version}")
        else:
            output_lines.append("-- No migration versions found")
        output_lines.append("")
        
        # Get all tables
        tables = await get_all_tables(engine)
        output_lines.append(f"-- Tables found: {len(tables)}")
        output_lines.append("")
        
        # Generate CREATE TABLE for each table
        for table_name in tables:
            output_lines.append(f"-- Table: {table_name}")
            create_sql = await generate_create_table_sql(engine, table_name)
            output_lines.append(create_sql)
            output_lines.append("")
        
        return "\n".join(output_lines)
        
    finally:
        await engine.dispose()


async def main():
    """Main entry point."""
    try:
        backup_content = await generate_schema_backup()
        print(backup_content)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
