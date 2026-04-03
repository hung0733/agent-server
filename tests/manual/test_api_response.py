#!/usr/bin/env python
"""Test API response to check JSON serialization of newlines."""
import asyncio
import json
from dotenv import load_dotenv

load_dotenv()

async def main():
    from api.dashboard import DashboardDataProvider
    from tools.task_queue import LocalTaskQueue
    from tools.task_dedup import TaskDedupService

    queue = LocalTaskQueue()
    dedup = TaskDedupService()
    provider = DashboardDataProvider(queue, dedup)

    # Get tasks data
    result = await provider.get_tasks(user_id=None)

    # Check first item
    if result["items"]:
        first_item = result["items"][0]
        summary = first_item.get("summary", "")

        print("=== API Response Analysis ===")
        print(f"Summary length: {len(summary)}")
        print(f"Contains actual newline (char 10): {chr(10) in summary}")
        print(f"First 200 chars (raw): {summary[:200]}")
        print()
        print(f"First 200 chars (repr): {repr(summary[:200])}")
        print()

        # Serialize to JSON and check
        json_str = json.dumps(first_item)
        print("=== After JSON serialization ===")
        print(f"JSON contains \\n: {'\\n' in json_str}")
        print(f"Sample JSON (first 300 chars): {json_str[:300]}")
        print()

        # Deserialize back
        deserialized = json.loads(json_str)
        deserialized_summary = deserialized["summary"]
        print("=== After JSON deserialization ===")
        print(f"Contains actual newline: {chr(10) in deserialized_summary}")
        print(f"First 200 chars (repr): {repr(deserialized_summary[:200])}")

if __name__ == "__main__":
    asyncio.run(main())
