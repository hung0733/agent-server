#!/usr/bin/env python3
"""檢查 checkpoint 入面嘅 data 結構"""
import asyncio
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from graph.graph_store import GraphStore
from utils.tools import Tools


async def check_checkpoint_data():
    await GraphStore.init_langgraph_checkpointer()
    schema = Tools.require_env('LANGGRAPH_SCHEMA')

    # Check checkpoint table structure
    async with GraphStore.pool.connection() as conn:
        result = await conn.execute(f'''
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = '{schema}'
            AND table_name = 'checkpoints'
            ORDER BY ordinal_position
        ''')
        columns = await result.fetchall()
        print('📊 Checkpoint table structure:')
        for col in columns:
            print(f'  {col[0]}: {col[1]}')

        # Count total checkpoints
        result = await conn.execute(f'''
            SELECT COUNT(*) FROM "{schema}".checkpoints
        ''')
        count = await result.fetchone()
        print(f'\n📈 Total checkpoints: {count[0]}')

        # Check multiple checkpoints to find one with messages
        result = await conn.execute(f'''
            SELECT thread_id, checkpoint_id, checkpoint
            FROM "{schema}".checkpoints
            WHERE checkpoint::text LIKE '%messages%'
            ORDER BY checkpoint_id DESC
            LIMIT 5
        ''')
        rows = await result.fetchall()

        if rows:
            print(f'\n🔍 Found {len(rows)} checkpoints with messages\n')

            for idx, row in enumerate(rows, 1):
                print(f'=== Checkpoint {idx} ===')
                checkpoint_data = row[2]

                if isinstance(checkpoint_data, dict):
                    if 'channel_values' in checkpoint_data:
                        channel_values = checkpoint_data['channel_values']
                        print(f'  channel_values keys: {list(channel_values.keys())}')

                        if 'messages' in channel_values:
                            msgs = channel_values['messages']
                            print(f'  Messages count: {len(msgs)}')
                            print(f'  Messages type: {type(msgs)}')

                            # Check first message
                            if msgs and len(msgs) > 0:
                                msg = msgs[0]
                                print(f'  First message type: {type(msg)}')

                                # Handle different message formats
                                if isinstance(msg, dict):
                                    print(f'    type: {msg.get("type", "N/A")}')
                                    print(f'    id: {msg.get("id", "N/A")}')
                                    content = msg.get("content", "N/A")
                                    if len(str(content)) > 50:
                                        print(f'    content: {str(content)[:50]}...')
                                    else:
                                        print(f'    content: {content}')
                                else:
                                    print(f'    raw: {str(msg)[:100]}...')
                        else:
                            print(f'  No messages key in channel_values')
                    else:
                        print(f'  No channel_values in checkpoint')
                else:
                    print(f'  checkpoint_data is not dict: {type(checkpoint_data)}')
                print()

            # Detail check on first checkpoint
            row = rows[0]
            print(f'\n📝 Sample checkpoint (latest):')
            print(f'  thread_id: {row[0]}')
            print(f'  checkpoint_id: {row[1]}')

            # Check checkpoint structure
            checkpoint_data = row[2]
            print(f'  checkpoint type: {type(checkpoint_data)}')

            if isinstance(checkpoint_data, dict):
                print(f'  checkpoint keys: {list(checkpoint_data.keys())}')

                # LangGraph stores state in channel_values
                if 'channel_values' in checkpoint_data:
                    channel_values = checkpoint_data['channel_values']
                    print(f'  channel_values keys: {list(channel_values.keys())}')

                    if 'messages' in channel_values:
                        msgs = channel_values['messages']
                    else:
                        msgs = None
                else:
                    msgs = None

                if msgs:
                    print(f'\n  📬 Messages:')
                    print(f'    count: {len(msgs)}')

                    # Check first message structure
                    if msgs:
                        first_msg = msgs[0]
                        print(f'\n    First message:')
                        print(f'      type: {type(first_msg)}')

                        if hasattr(first_msg, '__dict__'):
                            print(f'      attributes: {list(first_msg.__dict__.keys())}')
                            if hasattr(first_msg, 'id'):
                                print(f'      id: {first_msg.id}')
                            if hasattr(first_msg, 'content'):
                                content_preview = str(first_msg.content)[:100]
                                print(f'      content: {content_preview}...')
                        else:
                            print(f'      value: {first_msg}')

                    # Check last message structure
                    if len(msgs) > 1:
                        last_msg = msgs[-1]
                        print(f'\n    Last message:')
                        print(f'      type: {type(last_msg)}')
                        if hasattr(last_msg, 'id'):
                            print(f'      id: {last_msg.id}')
        else:
            print('\n⚠️  No checkpoints found')

    await GraphStore.pool.close()


if __name__ == '__main__':
    asyncio.run(check_checkpoint_data())
