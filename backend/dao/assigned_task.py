from datetime import datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import selectinload

from backend.dao.agent_type import AgentTypeDAO
from backend.dao.base import BaseDAO
from backend.entities.assigned_task import AssignedTask, AssignedTaskStep, AssignedTaskStepProcessLog
from backend.i18n import t


class AssignedTaskDAO(BaseDAO[AssignedTask]):
    model = AssignedTask

    async def get_by_task_id(self, task_id: str) -> AssignedTask | None:
        stmt = select(AssignedTask).where(AssignedTask.task_id == task_id)
        return await self.session.scalar(stmt)

    async def list_open_and_recent_finished(
        self,
        *,
        user_id: int,
        agent_id: int,
        since: datetime,
    ) -> list[AssignedTask]:
        finished_statuses = ("completed", "failed", "cancelled")
        stmt = (
            select(AssignedTask)
            .where(
                AssignedTask.user_id == user_id,
                AssignedTask.responsible_agent_id == agent_id,
                or_(
                    AssignedTask.status.not_in(finished_statuses),
                    and_(
                        AssignedTask.status.in_(finished_statuses),
                        AssignedTask.update_dt >= since,
                    ),
                ),
            )
            .order_by(AssignedTask.update_dt.desc())
        )
        return list((await self.session.scalars(stmt)).all())

    async def get_detail_by_task_id(
        self,
        *,
        user_id: int,
        agent_id: int,
        task_id: str,
    ) -> AssignedTask | None:
        stmt = (
            select(AssignedTask)
            .options(
                selectinload(AssignedTask.steps).selectinload(
                    AssignedTaskStep.agent_type_ref
                )
            )
            .where(
                AssignedTask.user_id == user_id,
                AssignedTask.responsible_agent_id == agent_id,
                AssignedTask.task_id == task_id,
            )
        )
        return await self.session.scalar(stmt)

    async def create_initial_steps(
        self,
        *,
        task_db_id: int,
        step_ids: tuple[str, str, str],
    ) -> list[AssignedTaskStep]:
        agent_type_dao = AgentTypeDAO(self.session)
        brainstormer = await agent_type_dao.get_or_create_by_code("brainstormer")
        planner = await agent_type_dao.get_or_create_by_code("planner")
        reviewer = await agent_type_dao.get_or_create_by_code("reviewer")
        steps = [
            AssignedTaskStep(
                step_id=step_ids[0],
                task_id=task_db_id,
                agent_type_id=brainstormer.id,
                agent_type_ref=brainstormer,
                title=t("tools.system.assign_task.step.brainstorm.title"),
                goal=t("tools.system.assign_task.step.brainstorm.goal"),
                status="pending",
                seq_no=1,
            ),
            AssignedTaskStep(
                step_id=step_ids[1],
                task_id=task_db_id,
                agent_type_id=planner.id,
                agent_type_ref=planner,
                title=t("tools.system.assign_task.step.planning.title"),
                goal=t("tools.system.assign_task.step.planning.goal"),
                status="blocked",
                seq_no=2,
            ),
            AssignedTaskStep(
                step_id=step_ids[2],
                task_id=task_db_id,
                agent_type_id=reviewer.id,
                agent_type_ref=reviewer,
                title=t("tools.system.assign_task.step.review.title"),
                goal=t("tools.system.assign_task.step.review.goal"),
                status="blocked",
                seq_no=3,
            ),
        ]
        self.session.add_all(steps)
        await self.session.flush()
        for step in steps:
            await self.session.refresh(step)
        steps[0].agent_type_ref = brainstormer
        steps[1].agent_type_ref = planner
        steps[2].agent_type_ref = reviewer
        return steps

    async def list_due_pending_steps(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[tuple[AssignedTaskStep, int]]:
        stmt = (
            select(AssignedTaskStep, AssignedTask.responsible_agent_id)
            .join(AssignedTask, AssignedTaskStep.task_id == AssignedTask.id)
            .options(
                selectinload(AssignedTaskStep.task).selectinload(
                    AssignedTask.responsible_agent
                ),
                selectinload(AssignedTaskStep.task).selectinload(AssignedTask.session),
                selectinload(AssignedTaskStep.agent_type_ref),
                selectinload(AssignedTaskStep.assign_agent),
                selectinload(AssignedTaskStep.session),
            )
            .where(
                AssignedTaskStep.status == "pending",
                or_(
                    AssignedTaskStep.next_run_at.is_(None),
                    AssignedTaskStep.next_run_at <= now,
                ),
            )
            .order_by(AssignedTaskStep.create_dt.asc(), AssignedTaskStep.seq_no.asc())
            .limit(limit)
        )

        rows = (await self.session.execute(stmt)).all()
        return [(row[0], row[1]) for row in rows]

    async def mark_step_processing(self, *, step_db_id: int, now: datetime) -> bool:
        stmt = (
            update(AssignedTaskStep)
            .where(
                AssignedTaskStep.id == step_db_id,
                AssignedTaskStep.status == "pending",
                or_(
                    AssignedTaskStep.next_run_at.is_(None),
                    AssignedTaskStep.next_run_at <= now,
                ),
            )
            .values(
                processing_started_at=func.coalesce(
                    AssignedTaskStep.processing_started_at,
                    now,
                )
            )
            .returning(AssignedTaskStep.id)
        )
        return (await self.session.scalar(stmt)) is not None

    async def update_task_session(
        self, *, task_db_id: int, session_db_id: int
    ) -> None:
        stmt = (
            update(AssignedTask)
            .where(AssignedTask.id == task_db_id)
            .values(session_id=session_db_id)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def update_step_assignment_and_session(
        self,
        *,
        step_db_id: int,
        assign_agent_db_id: int | None = None,
        session_db_id: int | None = None,
    ) -> None:
        values = {}
        if assign_agent_db_id is not None:
            values["assign_agent_id"] = assign_agent_db_id
        if session_db_id is not None:
            values["session_id"] = session_db_id
        if not values:
            return

        stmt = (
            update(AssignedTaskStep)
            .where(AssignedTaskStep.id == step_db_id)
            .values(**values)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def count_failed_process_logs(self, *, step_db_id: int) -> int:
        stmt = select(func.count()).select_from(AssignedTaskStepProcessLog).where(
            AssignedTaskStepProcessLog.step_id == step_db_id,
            AssignedTaskStepProcessLog.status == "failed",
        )
        return int(await self.session.scalar(stmt) or 0)

    async def count_process_logs(self, *, step_db_id: int) -> int:
        stmt = select(func.count()).select_from(AssignedTaskStepProcessLog).where(
            AssignedTaskStepProcessLog.step_id == step_db_id,
        )
        return int(await self.session.scalar(stmt) or 0)

    async def create_process_log(
        self,
        *,
        step_db_id: int,
        attempt_no: int,
        status: str,
        started_at: datetime,
        finished_at: datetime | None,
        log: str | None,
    ) -> AssignedTaskStepProcessLog:
        item = AssignedTaskStepProcessLog(
            step_id=step_db_id,
            attempt_no=attempt_no,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            log=log,
        )
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def finish_process_log(
        self,
        *,
        process_log_db_id: int | None,
        status: str,
        finished_at: datetime,
        log: str | None,
    ) -> None:
        if process_log_db_id is None:
            return

        stmt = (
            update(AssignedTaskStepProcessLog)
            .where(AssignedTaskStepProcessLog.id == process_log_db_id)
            .values(status=status, finished_at=finished_at, log=log)
        )
        await self.session.execute(stmt)
        await self.session.flush()
