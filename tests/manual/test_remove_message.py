#!/usr/bin/env python3
"""測試 RemoveMessage 功能"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from graph.graph_store import GraphStore
from agent.bulter import Bulter
from langchain_core.messages import RemoveMessage


async def test_remove_message():
    await GraphStore.init_langgraph_checkpointer()

    # Initialize the graph
    from graph.butler import workflow
    if not Bulter._graph:
        Bulter._graph = workflow.compile(checkpointer=GraphStore.checkpointer)

    # Get the thread with messages
    thread_id = "default-6bd4f52b-8cdf-42aa-88b8-91c1a542a121"
    config = {"configurable": {"thread_id": thread_id}}

    print(f"📋 Testing RemoveMessage on thread: {thread_id}\n")

    # Get initial state
    state_before = await Bulter._graph.aget_state(config)
    messages_before = state_before.values.get('messages', [])

    print(f"📊 BEFORE:")
    print(f"  Total messages: {len(messages_before)}")

    # Find messages with IDs
    messages_with_id = [m for m in messages_before if hasattr(m, 'id') and m.id is not None]
    print(f"  Messages with ID: {len(messages_with_id)}")

    if not messages_with_id:
        print("\n❌ No messages with ID found!")
        await GraphStore.pool.close()
        return

    # Show first 5 messages with ID
    print(f"\n  First 5 messages with ID:")
    for i, msg in enumerate(messages_with_id[:5], 1):
        content_preview = str(msg.content)[:50] if hasattr(msg, 'content') else 'N/A'
        print(f"    {i}. [{msg.type}] id={msg.id}, content={content_preview}...")

    # Try to delete the first 3 messages with ID
    to_delete = messages_with_id[:3]
    print(f"\n🗑️  Attempting to delete {len(to_delete)} messages...")

    delete_msgs = [RemoveMessage(id=m.id) for m in to_delete]

    print(f"\n📝 RemoveMessage objects created:")
    for i, rm in enumerate(delete_msgs, 1):
        print(f"  {i}. RemoveMessage(id={rm.id})")

    # Method 1: Using aupdate_state
    print(f"\n🔄 Method 1: Using aupdate_state...")
    try:
        await Bulter._graph.aupdate_state(
            config,
            {"messages": delete_msgs}
        )
        print("  ✅ aupdate_state executed without error")
    except Exception as e:
        print(f"  ❌ aupdate_state failed: {e}")
        import traceback
        traceback.print_exc()

    # Get state after deletion
    state_after = await Bulter._graph.aget_state(config)
    messages_after = state_after.values.get('messages', [])

    print(f"\n📊 AFTER:")
    print(f"  Total messages: {len(messages_after)}")
    messages_with_id_after = [m for m in messages_after if hasattr(m, 'id') and m.id is not None]
    print(f"  Messages with ID: {len(messages_with_id_after)}")

    # Check if deletion worked
    deleted_count = len(messages_before) - len(messages_after)
    print(f"\n📉 Messages deleted: {deleted_count}")

    if deleted_count > 0:
        print(f"  ✅ SUCCESS! {deleted_count} messages were deleted")
    else:
        print(f"  ❌ FAILED! No messages were deleted")

        # Debug: Check if the IDs we tried to delete still exist
        deleted_ids = {m.id for m in to_delete}
        still_exist = [m for m in messages_after if hasattr(m, 'id') and m.id in deleted_ids]

        if still_exist:
            print(f"\n  🔍 Debug: {len(still_exist)} of the 'deleted' messages still exist:")
            for msg in still_exist:
                content_preview = str(msg.content)[:50] if hasattr(msg, 'content') else 'N/A'
                print(f"    - [{msg.type}] id={msg.id}, content={content_preview}...")

    await GraphStore.pool.close()


if __name__ == '__main__':
    asyncio.run(test_remove_message())
