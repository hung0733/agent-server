#!/usr/bin/env python3
"""
Create a scheduled task to execute Bulter.review_ltm every minute.

This script creates:
1. A template task with task_type="review_ltm_scheduled"
2. A task schedule with interval type (PT1M = every 1 minute)

Usage:
    python scripts/create_review_ltm_task.py
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Load environment variables from .env
from dotenv import load_dotenv
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)
    print(f"✅ 已載入環境變數: {env_path}")
else:
    print(f"⚠️  未找到 .env 檔案: {env_path}")

from db.dao.task_dao import TaskDAO
from db.dao.task_schedule_dao import TaskScheduleDAO
from db.dao.user_dao import UserDAO
from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dto.task_dto import TaskCreate
from db.dto.task_schedule_dto import TaskScheduleCreate
from db.types import TaskStatus, Priority, ScheduleType


async def main():
    """Create review_ltm scheduled task."""
    print("🔧 正在創建 review_ltm 定時任務...")

    # 1. Get first user
    print("\n1️⃣ 查詢第一個 user...")
    users = await UserDAO.get_all(limit=1)
    if not users:
        print("❌ 錯誤：資料庫中沒有 user，請先創建 user")
        return

    user = users[0]
    print(f"   ✅ 找到 user: {user.id} ({user.username})")

    # 2. Get first agent instance
    print("\n2️⃣ 查詢第一個 agent instance...")
    agents = await AgentInstanceDAO.get_all(limit=1)
    if not agents:
        print("❌ 錯誤：資料庫中沒有 agent instance，請先創建 agent")
        return

    agent = agents[0]
    agent_id_str = agent.agent_id or "unknown"
    print(f"   ✅ 找到 agent: {agent.id} (agent_id: {agent_id_str})")

    # 3. Create template task
    print("\n3️⃣ 創建模板任務...")
    task_payload = {
        "task_execution_type": "method",
        "method_path": "agent.bulter@Bulter.review_ltm",
        "description": "Review long-term memory for unsummarized messages",
    }

    task = await TaskDAO.create(
        TaskCreate(
            user_id=user.id,
            agent_id=agent.id,
            task_type="review_ltm_scheduled",
            status=TaskStatus.pending,
            priority=Priority.normal,
            payload=task_payload,
            session_id=None,
        )
    )
    print(f"   ✅ 模板任務已創建: {task.id}")
    print(f"   📦 Payload: {task.payload}")

    # 4. Create schedule (every 1 minute using cron)
    print("\n4️⃣ 創建定時排程 (每分鐘執行一次)...")

    # Calculate next run time (1 minute from now)
    now_utc = datetime.now(timezone.utc)
    # Start from the next minute
    from datetime import timedelta
    next_run = now_utc + timedelta(minutes=1)
    next_run = next_run.replace(second=0, microsecond=0)

    schedule = await TaskScheduleDAO.create(
        TaskScheduleCreate(
            task_template_id=task.id,
            schedule_type=ScheduleType.cron,
            schedule_expression="* * * * *",  # Cron: every minute
            next_run_at=next_run,
            is_active=True,
        )
    )
    print(f"   ✅ 排程已創建: {schedule.id}")
    print(f"   ⏰ 下次執行時間: {schedule.next_run_at.isoformat()}")
    print(f"   📅 排程表達式: {schedule.schedule_expression} (cron: 每分鐘)")

    # 5. Summary
    print("\n" + "=" * 60)
    print("✅ review_ltm 定時任務創建成功！")
    print("=" * 60)
    print(f"Task ID:      {task.id}")
    print(f"Schedule ID:  {schedule.id}")
    print(f"Agent ID:     {agent_id_str}")
    print(f"User ID:      {user.id}")
    print(f"執行間隔:      每 1 分鐘")
    print(f"下次執行:      {schedule.next_run_at.isoformat()}")
    print(f"Method Path:  {task_payload['method_path']}")
    print("\n💡 提示：")
    print("   - Scheduler 會每分鐘掃描並執行到期任務")
    print("   - 可以在 logs 中查看執行結果")
    print("   - 要停止任務，請將 schedule.is_active 設為 False")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
