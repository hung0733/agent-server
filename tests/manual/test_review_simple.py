#!/usr/bin/env python3
"""簡單測試 review_stm 執行前後嘅 state"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from graph.graph_store import GraphStore
from agent.bulter import Bulter


async def test():
    await GraphStore.init_langgraph_checkpointer()

    # Initialize the graph
    from graph.butler import workflow
    if not Bulter._graph:
        Bulter._graph = workflow.compile(checkpointer=GraphStore.checkpointer)

    # Target thread
    thread_id = "default-6bd4f52b-8cdf-42aa-88b8-91c1a542a121"
    config = {"configurable": {"thread_id": thread_id}}

    print(f"📋 Thread: {thread_id}\n")

    # Get state BEFORE
    state_before = await Bulter._graph.aget_state(config)
    messages_before = state_before.values.get('messages', [])

    print(f"📊 Current state:")
    print(f"  Total messages: {len(messages_before)}")

    with_id = [m for m in messages_before if hasattr(m, 'id') and m.id is not None]
    without_id = [m for m in messages_before if not hasattr(m, 'id') or m.id is None]

    print(f"  Messages with ID: {len(with_id)}")
    print(f"  Messages without ID: {len(without_id)}")

    if without_id:
        print(f"\n⚠️  Found {len(without_id)} messages WITHOUT ID")
        print(f"     These were created with operator.add (before fix)")
        print(f"     They cannot be deleted using RemoveMessage")

    if with_id:
        print(f"\n✅ Found {len(with_id)} messages WITH ID")
        print(f"     These can be deleted using RemoveMessage")

        # Show some IDs
        print(f"\n  Sample message IDs:")
        for i, msg in enumerate(with_id[:3], 1):
            print(f"    {i}. {msg.id}")

    # Summary
    print(f"\n📝 Summary length: {len(state_before.values.get('summary', ''))} chars")

    # Check if messages need compression
    from utils.tools import Tools
    total_tokens = sum(Tools.get_token_count(str(m.content) if hasattr(m, 'content') else '') for m in messages_before)
    print(f"\n📊 Token count: {total_tokens}")

    # Trigger threshold
    trigger = 10000
    if total_tokens > trigger:
        print(f"  ⚠️  Exceeds trigger threshold ({trigger})")
        print(f"     review_stm SHOULD execute")
    else:
        print(f"  ✅ Below trigger threshold ({trigger})")
        print(f"     review_stm will NOT execute")

    await GraphStore.pool.close()


if __name__ == '__main__':
    asyncio.run(test())
