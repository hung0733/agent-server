#!/usr/bin/env python3
"""用 LangGraph API 直接讀取 state 檢查 messages ID"""
import asyncio
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from graph.graph_store import GraphStore
from agent.bulter import Bulter


async def check_state():
    await GraphStore.init_langgraph_checkpointer()

    # Initialize the graph
    from graph.butler import workflow
    if not Bulter._graph:
        Bulter._graph = workflow.compile(checkpointer=GraphStore.checkpointer)

    # Get a sample thread ID from the database
    from utils.tools import Tools
    schema = Tools.require_env('LANGGRAPH_SCHEMA')

    async with GraphStore.pool.connection() as conn:
        result = await conn.execute(f'''
            SELECT DISTINCT thread_id
            FROM "{schema}".checkpoint_writes
            WHERE channel = 'messages'
            LIMIT 1
        ''')
        row = await result.fetchone()
        if not row:
            print('❌ No threads found with messages')
            return

        thread_id = row[0]
        print(f'📋 Checking thread: {thread_id}')

    # Use LangGraph API to get state
    config = {"configurable": {"thread_id": thread_id}}

    try:
        state = await Bulter._graph.aget_state(config)

        print(f'\n📊 State info:')
        print(f'  values keys: {list(state.values.keys()) if state.values else "None"}')

        if state.values and 'messages' in state.values:
            messages = state.values['messages']
            print(f'\n📬 Messages in state:')
            print(f'  count: {len(messages)}')

            for idx, msg in enumerate(messages[:5], 1):  # Show first 5
                print(f'\n  Message {idx}:')
                print(f'    type: {type(msg).__name__}')
                print(f'    id: {msg.id if hasattr(msg, "id") else "N/A"}')

                if hasattr(msg, 'type'):
                    print(f'    message type: {msg.type}')

                if hasattr(msg, 'content'):
                    content = str(msg.content)
                    if len(content) > 50:
                        print(f'    content: {content[:50]}...')
                    else:
                        print(f'    content: {content}')

            # Summary
            messages_with_id = sum(1 for m in messages if hasattr(m, 'id') and m.id is not None)
            messages_without_id = len(messages) - messages_with_id

            print(f'\n📈 Summary:')
            print(f'  Total messages: {len(messages)}')
            print(f'  Messages with ID: {messages_with_id}')
            print(f'  Messages without ID: {messages_without_id}')

            if messages_without_id > 0:
                print(f'\n⚠️  Found {messages_without_id} messages WITHOUT ID!')
                print(f'     These messages cannot be deleted using RemoveMessage.')
            else:
                print(f'\n✅ All messages have IDs and can be deleted.')

        else:
            print('\n⚠️  No messages in state')

    except Exception as e:
        print(f'❌ Error: {e}')
        import traceback
        traceback.print_exc()

    await GraphStore.pool.close()


if __name__ == '__main__':
    asyncio.run(check_state())
