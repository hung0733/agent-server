#!/usr/bin/env python3
"""
Admin Script: Create scheduled review_msg task for an agent.

Creates a method-type task that runs daily message memory analysis for a specified agent.
The task calls Bulter.review_msg() every day at 01:00 UTC+8 (17:00 UTC).

Usage:
    python scripts/create_review_msg_schedule.py --agent-id otter
    python scripts/create_review_msg_schedule.py --agent-id otter --time "0 17 * * *"

Arguments:
    --agent-id: Agent instance agent_id (e.g., 'otter')
    --time: Optional cron expression (default: "0 17 * * *" = 01:00 UTC+8 daily)

Example:
    # Create daily 01:00 UTC+8 review_msg schedule
    python scripts/create_review_msg_schedule.py --agent-id otter

    # Custom time
    python scripts/create_review_msg_schedule.py --agent-id otter --time "0 20 * * *"
"""

import asyncio
import sys
import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from dotenv import load_dotenv

load_dotenv()

from logging_setup import setup_logging
setup_logging(level=logging.INFO)

from db.dao.task_dao import TaskDAO
from db.dao.task_schedule_dao import TaskScheduleDAO
from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dto.task_dto import TaskCreate
from db.dto.task_schedule_dto import TaskScheduleCreate
from db.types import TaskStatus, Priority, ScheduleType
from i18n import _
from scheduler.task_scheduler import calculate_next_run

logger = logging.getLogger(__name__)

# 01:00 UTC+8 = 17:00 UTC
DEFAULT_CRON = "0 17 * * *"
METHOD_PATH = "agent.bulter@Bulter.review_msg"


async def create_review_msg_schedule(
    agent_id_str: str,
    cron_expression: str = DEFAULT_CRON,
) -> bool:
    """
    Create a daily review_msg scheduled task for an agent.

    Args:
        agent_id_str: Agent instance agent_id (e.g., 'otter')
        cron_expression: Cron expression for schedule (default: 01:00 UTC+8 daily)

    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(
            _("[create_review_msg_schedule] 開始為 agent 創建 review_msg 排程: %s"),
            agent_id_str,
        )

        # 1. Find agent instance
        agent_instance = await AgentInstanceDAO.get_by_agent_id(agent_id_str)  # type: ignore
        if not agent_instance:
            logger.error(
                _("[create_review_msg_schedule] Agent 不存在: %s"),
                agent_id_str,
            )
            return False

        logger.info(
            _("[create_review_msg_schedule] ✅ 找到 Agent: %s (%s)"),
            agent_instance.name or agent_id_str,
            agent_instance.id,
        )

        # 2. Create task (method type)
        task_payload = {
            "task_execution_type": "method",
            "method_path": METHOD_PATH,
            "description": _("Daily Message Memory Review"),
        }

        task = await TaskDAO.create(
            TaskCreate(
                user_id=agent_instance.user_id,
                agent_id=agent_instance.id,
                task_type="scheduled_method",
                status=TaskStatus.pending,
                priority=Priority.normal,
                payload=task_payload,
            )
        )

        logger.info(
            _("[create_review_msg_schedule] ✅ Task 創建成功: %s"),
            task.id,
        )

        # 3. Create schedule
        next_run = calculate_next_run(
            cron_expression,
            ScheduleType.cron,
            datetime.now(timezone.utc),
        )

        schedule = await TaskScheduleDAO.create(
            TaskScheduleCreate(
                task_template_id=task.id,
                schedule_type=ScheduleType.cron,
                schedule_expression=cron_expression,
                is_active=True,
                next_run_at=next_run,
            )
        )

        logger.info(
            _("[create_review_msg_schedule] ✅ Schedule 創建成功: %s"),
            schedule.id,
        )

        # 4. Print summary
        print("\n" + "=" * 70)
        print(_("✅ review_msg 排程已成功創建！"))
        print("=" * 70)
        print(_("📋 詳細信息:"))
        print("")
        print(_("  Agent:"))
        print(f"    ID:       {agent_instance.id}")
        print(f"    名稱:     {agent_instance.name or agent_id_str}")
        print(f"    agent_id: {agent_id_str}")
        print("")
        print(_("  Task:"))
        print(f"    ID:   {task.id}")
        print(f"    類型: {task.task_type}")
        print(f"    方法: {task.payload['method_path']}")
        print("")
        print(_("  Schedule:"))
        print(f"    ID:       {schedule.id}")
        print(f"    類型:     {schedule.schedule_type}")
        print(f"    表達式:   {schedule.schedule_expression}")
        print(f"    下次執行: {next_run.isoformat() if next_run else 'N/A'}")
        print(f"    啟用:     {'✅ 是' if schedule.is_active else '❌ 否'}")
        print("")
        if cron_expression == DEFAULT_CRON:
            print(_("  執行頻率: ⏰ 每日 01:00 UTC+8 (17:00 UTC)"))
        else:
            print(f"  執行頻率: ⏰ Cron: {cron_expression}")
        print("")
        print("=" * 70)
        print("")

        logger.info(_("[create_review_msg_schedule] ✅ 完成！"))
        return True

    except Exception as e:
        logger.error(
            _("[create_review_msg_schedule] ❌ 失敗: %s"),
            str(e),
            exc_info=True,
        )
        print("\n" + "=" * 70)
        print(_("❌ 建立排程失敗"))
        print("=" * 70)
        print(f"錯誤: {str(e)}")
        print("=" * 70 + "\n")
        return False


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description=_("為 Agent 創建每日 review_msg 排程"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_("""
範例:
  # 創建每日 01:00 UTC+8 的 review_msg
  python scripts/create_review_msg_schedule.py --agent-id otter

  # 自訂時間
  python scripts/create_review_msg_schedule.py --agent-id otter --time "0 20 * * *"
        """),
    )

    parser.add_argument(
        "--agent-id",
        required=True,
        help=_("Agent instance ID (例如: otter)"),
    )
    parser.add_argument(
        "--time",
        default=DEFAULT_CRON,
        help=_("Cron 表達式 (預設: 每日 01:00 UTC+8 = \"0 17 * * *\")"),
    )

    args = parser.parse_args()

    success = await create_review_msg_schedule(
        args.agent_id,
        args.time,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n" + _("中止"))
        sys.exit(1)
    except Exception as e:
        logger.error(_("未預期的錯誤: %s"), str(e), exc_info=True)
        sys.exit(1)
