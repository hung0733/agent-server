#!/usr/bin/env python3
"""
Check the latest review_ltm execution result.

Usage:
    python scripts/check_latest_execution.py
"""
import asyncio
import sys
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
from db.dao.task_queue_dao import TaskQueueDAO


async def main():
    """Check latest execution result."""
    print("🔍 檢查最新執行結果...\n")

    # Get all tasks
    all_tasks = await TaskDAO.get_all(limit=100)
    template_tasks = [t for t in all_tasks if t.task_type == "review_ltm_scheduled" and t.parent_task_id is None]

    if not template_tasks:
        print("❌ 未找到模板任務")
        return

    # Find template with schedule
    from db.dao.task_schedule_dao import TaskScheduleDAO
    template_task = None
    for task in template_tasks:
        schedule = await TaskScheduleDAO.get_by_task_template_id(task.id)
        if schedule:
            template_task = task
            break

    if not template_task:
        print("❌ 未找到有排程的模板任務")
        return

    # Get execution instances
    execution_tasks = [t for t in all_tasks if t.parent_task_id == template_task.id]

    if not execution_tasks:
        print("ℹ️  尚未有執行實例")
        return

    # Get latest 3 executions
    latest_tasks = sorted(execution_tasks, key=lambda t: t.created_at, reverse=True)[:3]

    print(f"📊 最近 {len(latest_tasks)} 次執行結果：\n")

    for i, task in enumerate(latest_tasks, 1):
        print(f"{'='*60}")
        print(f"執行 #{i}")
        print(f"{'='*60}")
        print(f"Task ID:   {task.id}")
        print(f"Status:    {task.status}")
        print(f"Created:   {task.created_at.isoformat()}")
        print(f"Started:   {task.started_at.isoformat() if task.started_at else 'N/A'}")
        print(f"Completed: {task.completed_at.isoformat() if task.completed_at else 'N/A'}")

        if task.result:
            print(f"\n📦 執行結果：")
            result = task.result
            if isinstance(result, dict):
                for key, value in result.items():
                    print(f"   {key}: {value}")
            else:
                print(f"   {result}")

        if task.error_message:
            print(f"\n❌ 錯誤訊息：")
            print(f"   {task.error_message}")

        print()

    print("\n💡 提示：如果最新執行的 result 仍然顯示 total_groups=0，")
    print("   請稍等 1 分鐘，讓定時任務再次執行並使用更新後的查詢條件。")


if __name__ == "__main__":
    asyncio.run(main())
