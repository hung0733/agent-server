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


class AssignedTaskRead(AssignedTaskCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class AssignedTaskStepCreate(BaseModel):
    step_id: str
    task_id: int
    parent_step_id: int | None = None
    step_type: str
    title: str
    goal: str
    status: str
    seq_no: int
    assign_agent_id: int
    session_id: int | None = None
    output_html: str | None = None
    output_json: str | None = None


class AssignedTaskStepRead(AssignedTaskStepCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
