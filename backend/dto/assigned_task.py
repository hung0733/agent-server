from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AssignedTaskCreate(BaseModel):
    task_id: str
    user_id: int
    responsible_agent_id: int
    session_id: int | None = None
    task_name: str
    goal: str
    status: str = "brainstorm_pending"
    approved_plan_html: str | None = None
    planned_task_step_json: str | None = None


class AssignedTaskRead(AssignedTaskCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class AssignedTaskStepCreate(BaseModel):
    step_id: str
    task_id: int
    parent_step_id: int | None = None
    agent_type_id: int | None = None
    agent_type: str | None = None
    title: str
    goal: str
    status: str
    seq_no: int
    review_suggest: str | None = None
    assign_agent_id: int | None = None
    session_id: int | None = None
    output_html: str | None = None
    output_json: str | None = None


class AssignedTaskStepRead(AssignedTaskStepCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class AssignedTaskStepProcessLogCreate(BaseModel):
    step_id: int
    attempt_no: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    log: str | None = None


class AssignedTaskStepProcessLogRead(AssignedTaskStepProcessLogCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
