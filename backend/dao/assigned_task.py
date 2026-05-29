from sqlalchemy import select

from backend.dao.base import BaseDAO
from backend.entities.assigned_task import AssignedTask, AssignedTaskStep
from backend.i18n import t


class AssignedTaskDAO(BaseDAO[AssignedTask]):
    model = AssignedTask

    async def get_by_task_id(self, task_id: str) -> AssignedTask | None:
        stmt = select(AssignedTask).where(AssignedTask.task_id == task_id)
        return await self.session.scalar(stmt)

    async def create_initial_steps(
        self,
        *,
        task_db_id: int,
        assign_agent_id: int,
        step_ids: tuple[str, str, str],
    ) -> list[AssignedTaskStep]:
        steps = [
            AssignedTaskStep(
                step_id=step_ids[0],
                task_id=task_db_id,
                step_type="brainstorm",
                title=t("tools.system.assign_task.step.brainstorm.title"),
                goal=t("tools.system.assign_task.step.brainstorm.goal"),
                status="pending",
                seq_no=1,
                assign_agent_id=assign_agent_id,
            ),
            AssignedTaskStep(
                step_id=step_ids[1],
                task_id=task_db_id,
                step_type="planning",
                title=t("tools.system.assign_task.step.planning.title"),
                goal=t("tools.system.assign_task.step.planning.goal"),
                status="blocked",
                seq_no=2,
                assign_agent_id=assign_agent_id,
            ),
            AssignedTaskStep(
                step_id=step_ids[2],
                task_id=task_db_id,
                step_type="review",
                title=t("tools.system.assign_task.step.review.title"),
                goal=t("tools.system.assign_task.step.review.goal"),
                status="blocked",
                seq_no=3,
                assign_agent_id=assign_agent_id,
            ),
        ]
        self.session.add_all(steps)
        await self.session.flush()
        for step in steps:
            await self.session.refresh(step)
        return steps
