#!/usr/bin/env python3
"""手動測試刪除邏輯"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from graph.graph_store import GraphStore
from agent.bulter import Bulter
from langchain_core.messages import RemoveMessage
from utils.tools import Tools


async def test():
    await GraphStore.init_langgraph_checkpointer()

    # Initialize the graph
    from graph.butler import workflow
    if not Bulter._graph:
        Bulter._graph = workflow.compile(checkpointer=GraphStore.checkpointer)

    # Target thread
    thread_id = "default-6bd4f52b-8cdf-42aa-88b8-91c1a542a121"
    config = {"configurable": {"thread_id": thread_id}}

    print(f"📋 Testing manual delete on thread: {thread_id}\n")

    # Get state BEFORE
    state_before = await Bulter._graph.aget_state(config)
    messages_before = state_before.values.get('messages', [])

    print(f"📊 BEFORE:")
    print(f"  Total messages: {len(messages_before)}")

    # Calculate tokens and split point (same logic as review_stm)
    SUMMARY_USAGE_TOKEN = 5000
    tokens = 0
    split_idx = 0

    for i, m in enumerate(messages_before):
        content = m.content if hasattr(m, 'content') else ''
        tokens += Tools.get_token_count(str(content))
        if tokens >= SUMMARY_USAGE_TOKEN:
            split_idx = i + 1
            # Ensure conversation completeness
            while (
                split_idx < len(messages_before)
                and messages_before[split_idx].type != "human"
            ):
                split_idx += 1
            break

    if split_idx == 0 or split_idx >= len(messages_before):
        split_idx = max(1, len(messages_before) // 2)

    old_messages = messages_before[:split_idx]

    print(f"  Split index: {split_idx}")
    print(f"  Messages to delete: {len(old_messages)}")

    # Check IDs
    messages_with_id = [m for m in old_messages if hasattr(m, 'id') and m.id is not None]
    messages_without_id = [m for m in old_messages if not hasattr(m, 'id') or m.id is None]

    print(f"    - With ID: {len(messages_with_id)}")
    print(f"    - Without ID: {len(messages_without_id)}")

    if len(messages_without_id) > 0:
        print(f"\n  ⚠️  {len(messages_without_id)} messages don't have IDs - will NOT be deleted")

    # Create RemoveMessage list (only for messages with ID)
    delete_msgs = [RemoveMessage(id=m.id) for m in old_messages if m.id is not None]

    print(f"\n🗑️  Attempting to delete {len(delete_msgs)} messages with RemoveMessage...")

    if len(delete_msgs) == 0:
        print(f"  ❌ No messages to delete (all lack IDs)!")
        await GraphStore.pool.close()
        return

    # Execute deletion
    try:
        await Bulter._graph.aupdate_state(
            config,
            {"messages": delete_msgs}
        )
        print(f"  ✅ aupdate_state executed")
    except Exception as e:
        print(f"  ❌ aupdate_state failed: {e}")
        import traceback
        traceback.print_exc()
        await GraphStore.pool.close()
        return

    # Get state AFTER
    state_after = await Bulter._graph.aget_state(config)
    messages_after = state_after.values.get('messages', [])

    print(f"\n📊 AFTER:")
    print(f"  Total messages: {len(messages_after)}")

    # Check results
    deleted_count = len(messages_before) - len(messages_after)
    print(f"\n📉 Messages deleted: {deleted_count}")

    if deleted_count > 0:
        print(f"  ✅ SUCCESS! Deleted {deleted_count} messages")
    else:
        print(f"  ❌ FAILED! No messages were deleted")

        # Debug: check if the IDs still exist
        deleted_ids = {m.id for m in old_messages if hasattr(m, 'id') and m.id}
        still_exist = [m for m in messages_after if hasattr(m, 'id') and m.id in deleted_ids]

        if still_exist:
            print(f"\n  🔍 {len(still_exist)} 'deleted' messages still exist:")
            for msg in still_exist[:3]:
                content_preview = str(msg.content)[:50] if hasattr(msg, 'content') else 'N/A'
                print(f"    - [{msg.type}] id={msg.id}, content={content_preview}...")

    await GraphStore.pool.close()


if __name__ == '__main__':
    asyncio.run(test())
