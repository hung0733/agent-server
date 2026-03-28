#!/usr/bin/env python3
"""
Directly test the review_ltm method with updated code.

Usage:
    python tests/manual/test_review_ltm.py
"""
import asyncio
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root / "src"))

# Load environment variables from .env
from dotenv import load_dotenv
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)

from agent.bulter import Bulter


async def main():
    """Test review_ltm directly."""
    print("🧪 直接測試 review_ltm 方法...\n")

    # Use the agent_id from debug
    agent_id = "agent-6bd4f52b-8cdf-42aa-88b8-91c1a542a121"

    print(f"Agent ID: {agent_id}")
    print(f"開始執行 review_ltm...\n")

    result = await Bulter.review_ltm(agent_id=agent_id)

    print("\n" + "="*60)
    print("📊 執行結果")
    print("="*60)
    for key, value in result.items():
        print(f"{key}: {value}")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
