#!/usr/bin/env python3
"""
Run LTM database schema migration
"""
import asyncio
import asyncpg
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def run_migration():
    """Execute the LTM schema migration"""
    # Get PostgreSQL connection parameters
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    user = os.getenv("POSTGRES_USER", "agentserver")
    password = os.getenv("POSTGRES_PASSWORD", "")
    database = os.getenv("POSTGRES_DB", "agentserver")

    print(f"📊 Connecting to PostgreSQL: {user}@{host}:{port}/{database}")

    # Read migration SQL file
    migration_file = Path(__file__).parent.parent / "src" / "ltm" / "database" / "migrations" / "001_init_schema.sql"

    if not migration_file.exists():
        print(f"❌ Migration file not found: {migration_file}")
        return False

    with open(migration_file, 'r', encoding='utf-8') as f:
        migration_sql = f.read()

    print(f"📄 Read migration file: {migration_file.name}")
    print(f"📝 SQL length: {len(migration_sql)} characters")

    # Execute migration
    try:
        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
        )

        print("🔄 Executing migration...")
        await conn.execute(migration_sql)

        # Verify tables created
        tables = await conn.fetch("""
            SELECT tablename
            FROM pg_tables
            WHERE schemaname = 'public'
            AND tablename = 'dialogues'
        """)

        if tables:
            print("✅ Migration successful! Tables created:")
            for table in tables:
                print(f"   - {table['tablename']}")
        else:
            print("⚠️  Migration executed but no tables found")

        await conn.close()
        return True

    except Exception as e:
        print(f"❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(run_migration())
    exit(0 if success else 1)
