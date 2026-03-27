#!/usr/bin/env python3
"""
Admin Script: Create scheduled LTM review task for an agent.

Creates a method-type task that runs a daily LTM review for a specified agent.
The review will trigger every day at 12:00 UTC using the review_ltm() method.

Usage:
    python scripts/create_ltm_review_schedule.py --agent-id butler-001
    python scripts/create_ltm_review_schedule.py --agent-id butler-001 --time "0 14 * * *"

Arguments:
    --agent-id: Agent instance agent_id (e.g., 'butler-001')
    --time: Optional cron expression (default: "0 12 * * *" = 12:00 UTC daily)

Example:
    # Create daily 12:00 UTC LTM review
    python scripts/create_ltm_review_schedule.py --agent-id butler-001

    # Create daily 14:00 UTC LTM review
    python scripts/create_ltm_review_schedule.py --agent-id butler-001 --time "0 14 * * *"

    # Create weekly (Monday at 12:00 UTC) LTM review
    python scripts/create_ltm_review_schedule.py --agent-id butler-001 --time "0 12 * * 1"
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
from db.types import TaskStatus, Priority, ScheduleType, TaskExecutionType
from i18n import _
from uuid import UUID
from scheduler.task_scheduler import calculate_next_run

logger = logging.getLogger(__name__)


async def create_ltm_review_schedule(
    agent_id_str: str,
    cron_expression: str = "0 12 * * *",
) -> bool:
    """
    Create a daily LTM review scheduled task for an agent.

    Args:
        agent_id_str: Agent instance agent_id (e.g., 'butler-001')
        cron_expression: Cron expression for schedule (default: daily 12:00 UTC)

    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(
            _("[create_ltm_review_schedule] 開始為 agent 創建 LTM 排程: %s"),
            agent_id_str,
        )

        # 1. Find agent instance
        agent_instance = await AgentInstanceDAO.get_by_agent_id(agent_id_str) # type: ignore
        if not agent_instance:
            logger.error(
                _("[create_ltm_review_schedule] Agent 不存在: %s"),
                agent_id_str,
            )
            return False

        logger.info(
            _("[create_ltm_review_schedule] ✅ 找到 Agent: %s (%s)"),
            agent_instance.name or agent_id_str,
            agent_instance.id,
        )

        # 2. Create task (method type)
        task_payload = {
            "task_execution_type": "method",
            "method_path": "src.agent.bulter@Bulter.review_ltm",
            "description": _("Daily Long-Term Memory Review"),
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
            _("[create_ltm_review_schedule] ✅ Task 創建成功: %s"),
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
            _("[create_ltm_review_schedule] ✅ Schedule 創建成功: %s"),
            schedule.id,
        )

        # 4. Print summary
        print("\n" + "=" * 70)
        print(_("✅ LTM Review 排程已成功創建！"))
        print("=" * 70)
        print(_("📋 詳細信息:"))
        print("")
        print(_("  Agent:"))
        print(f"    ID:     {agent_instance.id}")
        print(f"    名稱:   {agent_instance.name or agent_id_str}")
        print(f"    agent_id: {agent_id_str}")
        print("")
        print(_("  Task:"))
        print(f"    ID:     {task.id}")
        print(f"    類型:   {task.task_type}")
        print(f"    方法:   {task.payload['method_path']}")
        print("")
        print(_("  Schedule:"))
        print(f"    ID:     {schedule.id}")
        print(f"    類型:   {schedule.schedule_type}")
        print(f"    表達式: {schedule.schedule_expression}")
        print(f"    下次執行: {next_run.isoformat() if next_run else 'N/A'}")
        print(f"    啟用:   {'✅ 是' if schedule.is_active else '❌ 否'}")
        print("")
        print(_("  執行頻率: "))
        if cron_expression == "0 12 * * *":
            print(_("    ⏰ 每日 12:00 UTC"))
        elif cron_expression == "0 12 * * 1":
            print(_("    ⏰ 每週一 12:00 UTC"))
        else:
            print(f"    ⏰ Cron: {cron_expression}")
        print("")
        print("=" * 70)
        print("")

        logger.info(_("[create_ltm_review_schedule] ✅ 完成！"))
        return True

    except Exception as e:
        logger.error(
            _("[create_ltm_review_schedule] ❌ 失敗: %s"),
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
        description=_("為 Agent 創建每日 LTM Review 排程"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_("""
範例:
  # 創建每日 12:00 UTC 的 review
  python scripts/create_ltm_review_schedule.py --agent-id butler-001

  # 創建每日 14:00 UTC 的 review
  python scripts/create_ltm_review_schedule.py --agent-id butler-001 --time "0 14 * * *"

  # 創建每週一 12:00 UTC 的 review
  python scripts/create_ltm_review_schedule.py --agent-id butler-001 --time "0 12 * * 1"
        """),
    )

    parser.add_argument(
        "--agent-id",
        required=True,
        help=_("Agent instance ID (例如: butler-001)"),
    )
    parser.add_argument(
        "--time",
        default="0 12 * * *",
        help=_("Cron 表達式 (預設: 每日 12:00 UTC)"),
    )

    args = parser.parse_args()

    success = await create_ltm_review_schedule(
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
