#!/usr/bin/env python3
"""
Fix LTM database schema - drop old table and recreate with TEXT types
"""
import asyncio
import asyncpg
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def fix_schema():
    """Drop old dialogues table and recreate with correct schema"""
    # Get PostgreSQL connection parameters
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    user = os.getenv("POSTGRES_USER", "agentserver")
    password = os.getenv("POSTGRES_PASSWORD", "")
    database = os.getenv("POSTGRES_DB", "agentserver")

    print(f"📊 Connecting to PostgreSQL: {user}@{host}:{port}/{database}")

    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
        )

        # Drop old tables if exist (both public and simpleme schemas)
        print("🗑️  Dropping old dialogues tables (if exist)...")
        await conn.execute("DROP TABLE IF EXISTS public.dialogues CASCADE")
        await conn.execute("DROP TABLE IF EXISTS simpleme.dialogues CASCADE")
        await conn.execute("DROP TABLE IF EXISTS ltm.dialogues CASCADE")
        print("✅ Old tables dropped")

        # Read and execute migration
        migration_file = Path(__file__).parent.parent / "src" / "ltm" / "database" / "migrations" / "001_init_schema.sql"

        with open(migration_file, 'r', encoding='utf-8') as f:
            migration_sql = f.read()

        print(f"📄 Executing migration: {migration_file.name}")
        await conn.execute(migration_sql)

        # Verify new schema
        columns = await conn.fetch("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'dialogues'
            ORDER BY ordinal_position
        """)

        if columns:
            print("✅ New schema created successfully:")
            for col in columns:
                nullable = "NULL" if col['is_nullable'] == 'YES' else "NOT NULL"
                print(f"   - {col['column_name']}: {col['data_type']} {nullable}")
        else:
            print("❌ Failed to create table")

        await conn.close()
        return True

    except Exception as e:
        print(f"❌ Schema fix failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(fix_schema())
    exit(0 if success else 1)
