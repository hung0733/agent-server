#!/usr/bin/env python3
"""檢查 checkpoint_writes 入面嘅 messages"""
import asyncio
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from graph.graph_store import GraphStore
from utils.tools import Tools


async def check_checkpoint_writes():
    await GraphStore.init_langgraph_checkpointer()
    schema = Tools.require_env('LANGGRAPH_SCHEMA')

    async with GraphStore.pool.connection() as conn:
        # Check tables
        result = await conn.execute(f'''
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = '{schema}'
        ''')
        tables = await result.fetchall()
        print(f'📊 Tables in {schema}:')
        for table in tables:
            print(f'  - {table[0]}')

        # Check checkpoint_writes structure
        if any('writes' in t[0] for t in tables):
            result = await conn.execute(f'''
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = '{schema}'
                AND table_name LIKE '%writes%'
                ORDER BY ordinal_position
            ''')
            columns = await result.fetchall()
            print(f'\n📋 Checkpoint writes table structure:')
            for col in columns:
                print(f'  {col[0]}: {col[1]}')

            # Count writes
            result = await conn.execute(f'''
                SELECT COUNT(*) FROM "{schema}".checkpoint_writes
            ''')
            count = await result.fetchone()
            print(f'\n📈 Total writes: {count[0]}')

            # Check for messages in writes
            result = await conn.execute(f'''
                SELECT thread_id, checkpoint_id, task_id, channel, type, blob
                FROM "{schema}".checkpoint_writes
                WHERE channel = 'messages'
                ORDER BY checkpoint_id DESC
                LIMIT 10
            ''')
            rows = await result.fetchall()

            if rows:
                print(f'\n🔍 Found {len(rows)} writes to messages channel\n')

                for idx, row in enumerate(rows, 1):
                    print(f'=== Write {idx} ===')
                    print(f'  thread_id: {row[0]}')
                    print(f'  checkpoint_id: {row[1]}')
                    print(f'  task_id: {row[2]}')
                    print(f'  channel: {row[3]}')
                    print(f'  type: {row[4]}')

                    blob = row[5]
                    print(f'  blob type: {type(blob)}')
                    print(f'  blob size: {len(blob) if blob else 0} bytes')

                    # Try to deserialize blob
                    if blob:
                        try:
                            # LangGraph uses msgpack for serialization
                            import msgpack
                            value = msgpack.unpackb(blob, raw=False)
                            print(f'  deserialized type: {type(value)}')

                            if isinstance(value, (list, tuple)):
                                print(f'  messages count: {len(value)}')
                                if value:
                                    msg = value[0]
                                    print(f'  First message type: {type(msg)}')

                                    # Check if it's a LangChain message object
                                    if hasattr(msg, 'id'):
                                        print(f'    id: {msg.id}')
                                    if hasattr(msg, 'type'):
                                        print(f'    type: {msg.type}')
                                    if hasattr(msg, 'content'):
                                        content = str(msg.content)
                                        if len(content) > 50:
                                            print(f'    content: {content[:50]}...')
                                        else:
                                            print(f'    content: {content}')

                                    # If it's a dict
                                    if isinstance(msg, dict):
                                        print(f'    dict id: {msg.get("id", "N/A")}')
                                        print(f'    dict type: {msg.get("type", "N/A")}')
                        except Exception as e:
                            print(f'  ❌ Failed to deserialize: {e}')
                    print()

    await GraphStore.pool.close()


if __name__ == '__main__':
    asyncio.run(check_checkpoint_writes())
