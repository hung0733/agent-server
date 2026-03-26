#!/usr/bin/env python3
"""
測試 script：檢查 LangGraph checkpoint 入面嘅 messages 有咩 attributes
"""
import asyncio
import os
import sys
from datetime import datetime

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from graph.graph_store import GraphStore


async def main():
    # Initialize GraphStore
    print("初始化 GraphStore...")
    checkpointer, pool = await GraphStore.init_langgraph_checkpointer()

    # Get a test thread state
    test_thread_id = "default-6bd4f52b-8cdf-42aa-88b8-91c1a542a121"

    print(f"\n檢查 thread: {test_thread_id}")

    # Get state
    config = {"configurable": {"thread_id": test_thread_id}}
    state = await checkpointer.aget(config)  # type: ignore

    if not state:
        print("❌ 搵唔到 state")
        await pool.close()
        return

    messages = state.get("channel_values", {}).get("messages", [])
    print(f"\n找到 {len(messages)} 條訊息")

    # Inspect first 3 messages
    for i, msg in enumerate(messages[:3]):
        print(f"\n{'='*60}")
        print(f"Message {i+1}:")
        print(f"  Type: {type(msg).__name__}")
        print(f"  Has id: {hasattr(msg, 'id')}")
        if hasattr(msg, "id"):
            print(f"  id value: {msg.id}")
        print(f"  Has additional_kwargs: {hasattr(msg, 'additional_kwargs')}")
        if hasattr(msg, "additional_kwargs"):
            print(f"  additional_kwargs: {msg.additional_kwargs}")
        print(f"  Has created_at: {hasattr(msg, 'created_at')}")
        if hasattr(msg, "created_at"):
            print(f"  created_at: {msg.created_at}")
        print(f"  Has response_metadata: {hasattr(msg, 'response_metadata')}")
        if hasattr(msg, "response_metadata"):
            print(f"  response_metadata: {msg.response_metadata}")

        # Check all attributes
        print(f"  All attributes containing 'time' or 'date':")
        for attr in dir(msg):
            if "time" in attr.lower() or "date" in attr.lower():
                try:
                    val = getattr(msg, attr)
                    print(f"    {attr}: {val}")
                except:
                    pass

    await pool.close()
    print("\n完成！")


if __name__ == "__main__":
    asyncio.run(main())
