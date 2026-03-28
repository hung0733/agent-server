#!/usr/bin/env python3
"""
Check the status of review_ltm scheduled task executions.

This script queries:
1. The template task status
2. Recent execution instances (child tasks)
3. Task queue entries
4. Schedule information

Usage:
    python scripts/check_review_ltm_task.py
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

from db.dao.task_dao import TaskDAO
from db.dao.task_schedule_dao import TaskScheduleDAO
from db.dao.task_queue_dao import TaskQueueDAO


async def main():
    """Check review_ltm task status."""
    print("🔍 檢查 review_ltm 定時任務狀態...\n")

    # 1. Find all review_ltm_scheduled template tasks
    print("1️⃣ 查詢模板任務...")
    all_tasks = await TaskDAO.get_all(limit=100)
    template_tasks = [t for t in all_tasks if t.task_type == "review_ltm_scheduled" and t.parent_task_id is None]

    if not template_tasks:
        print("   ❌ 未找到 review_ltm_scheduled 模板任務")
        return

    print(f"   ✅ 找到 {len(template_tasks)} 個模板任務")

    # Try to find one with a schedule
    template_task = None
    for task in template_tasks:
        schedule = await TaskScheduleDAO.get_by_task_template_id(task.id)
        if schedule:
            template_task = task
            print(f"   🎯 使用有排程的模板任務: {task.id}")
            break

    if not template_task:
        # Use the latest one
        template_task = template_tasks[-1]
        print(f"   ⚠️  使用最新模板任務（可能無排程）: {template_task.id}")

    print(f"   📦 Status: {template_task.status}")
    print(f"   👤 Agent ID: {template_task.agent_id}")
    print(f"   📝 Payload: {template_task.payload}")

    # 2. Get schedule for this template
    print("\n2️⃣ 查詢排程...")
    schedule = await TaskScheduleDAO.get_by_task_template_id(template_task.id)
    if not schedule:
        print("   ❌ 未找到排程")
        return

    now_utc = datetime.now(timezone.utc)
    print(f"   ✅ 找到排程: {schedule.id}")
    print(f"   🔄 Schedule Type: {schedule.schedule_type}")
    print(f"   📅 Expression: {schedule.schedule_expression}")
    print(f"   ✔️  Active: {schedule.is_active}")
    print(f"   ⏰ Next Run: {schedule.next_run_at.isoformat() if schedule.next_run_at else 'None'}")
    print(f"   📆 Last Run: {schedule.last_run_at.isoformat() if schedule.last_run_at else 'None'}")
    print(f"   🕐 Current Time: {now_utc.isoformat()}")

    if schedule.next_run_at:
        if schedule.next_run_at <= now_utc:
            print(f"   ⏳ 任務已到期，等待執行...")
        else:
            time_until = (schedule.next_run_at - now_utc).total_seconds()
            print(f"   ⏳ 距離下次執行還有 {int(time_until)} 秒")

    # 3. Get execution instances (child tasks)
    print("\n3️⃣ 查詢執行實例...")
    execution_tasks = [t for t in all_tasks if t.parent_task_id == template_task.id]

    if not execution_tasks:
        print("   ℹ️  尚未有執行實例（任務未到期或scheduler未運行）")
    else:
        print(f"   ✅ 找到 {len(execution_tasks)} 個執行實例:")
        for i, task in enumerate(execution_tasks[-5:], 1):  # Show last 5
            print(f"\n   執行實例 #{i}:")
            print(f"      ID: {task.id}")
            print(f"      Status: {task.status}")
            print(f"      Created: {task.created_at.isoformat()}")
            print(f"      Started: {task.started_at.isoformat() if task.started_at else 'N/A'}")
            print(f"      Completed: {task.completed_at.isoformat() if task.completed_at else 'N/A'}")
            if task.result:
                print(f"      Result: {task.result}")
            if task.error_message:
                print(f"      Error: {task.error_message[:200]}")

    # 4. Get task queue entries
    print("\n4️⃣ 查詢任務隊列...")
    queue_entries = await TaskQueueDAO.get_all(limit=100)
    related_queue = [q for q in queue_entries if any(q.task_id == t.id for t in execution_tasks)]

    if not related_queue:
        print("   ℹ️  尚未有隊列記錄")
    else:
        print(f"   ✅ 找到 {len(related_queue)} 個隊列記錄:")
        for i, queue in enumerate(related_queue[-5:], 1):  # Show last 5
            print(f"\n   隊列記錄 #{i}:")
            print(f"      Task ID: {queue.task_id}")
            print(f"      Status: {queue.status}")
            print(f"      Priority: {queue.priority}")
            print(f"      Scheduled: {queue.scheduled_at.isoformat() if queue.scheduled_at else 'N/A'}")
            print(f"      Started: {queue.started_at.isoformat() if queue.started_at else 'N/A'}")
            print(f"      Completed: {queue.completed_at.isoformat() if queue.completed_at else 'N/A'}")

    # 5. Summary
    print("\n" + "=" * 60)
    print("📊 總結")
    print("=" * 60)
    print(f"模板任務 ID: {template_task.id}")
    print(f"排程狀態: {'活躍' if schedule.is_active else '未活躍'}")
    print(f"執行次數: {len(execution_tasks)}")
    print(f"隊列記錄: {len(related_queue)}")

    if schedule.is_active and schedule.next_run_at:
        if schedule.next_run_at <= now_utc:
            print("\n💡 提示: 任務已到期，如果 scheduler 正在運行，應該很快會執行")
        else:
            minutes_until = int((schedule.next_run_at - now_utc).total_seconds() / 60)
            print(f"\n💡 提示: 下次執行在 {minutes_until} 分鐘後")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
