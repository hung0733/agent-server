from langchain_core.tools import tool
from pydantic import BaseModel, Field

from backend.i18n import t


class AskUserQuestionArgs(BaseModel):
    question: str = Field(
        description=t("tools.brainstormer.ask_user_question.question.description")
    )
    description: str = Field(
        description=t("tools.brainstormer.ask_user_question.description.description")
    )
    choose: list[str] = Field(
        description=t("tools.brainstormer.ask_user_question.choose.description")
    )


class SubmitHtmlPlanForApprovalArgs(BaseModel):
    task_id: str = Field(
        description=t(
            "tools.brainstormer.submit_html_plan_for_approval.task_id.description"
        )
    )
    task_name: str = Field(
        description=t(
            "tools.brainstormer.submit_html_plan_for_approval.task_name.description"
        )
    )
    goal: str = Field(
        description=t(
            "tools.brainstormer.submit_html_plan_for_approval.goal.description"
        )
    )
    html_plan: str = Field(
        description=t(
            "tools.brainstormer.submit_html_plan_for_approval.html_plan.description"
        )
    )


@tool(
    args_schema=AskUserQuestionArgs,
    description=t("tools.brainstormer.ask_user_question.description"),
)
async def ask_user_question(
    question: str,
    description: str,
    choose: list[str],
) -> str:
    question = question.strip()
    description = description.strip()
    choices = [item.strip() for item in choose if item.strip()]

    if not question:
        return t("tools.brainstormer.ask_user_question.blank_question")
    if not description:
        return t("tools.brainstormer.ask_user_question.blank_description")
    if not choices:
        return t("tools.brainstormer.ask_user_question.blank_choose")

    choices_text = "\n".join(
        t("tools.brainstormer.ask_user_question.choice_line") % (index, choice)
        for index, choice in enumerate(choices, start=1)
    )
    return t("tools.brainstormer.ask_user_question.output") % (
        question,
        description,
        choices_text,
    )


@tool(
    args_schema=SubmitHtmlPlanForApprovalArgs,
    description=t("tools.brainstormer.submit_html_plan_for_approval.description"),
)
async def submit_html_plan_for_approval(
    task_id: str,
    task_name: str,
    goal: str,
    html_plan: str,
) -> str:
    task_id = task_id.strip()
    task_name = task_name.strip()
    goal = goal.strip()
    html_plan = html_plan.strip()

    if not task_id:
        return t("tools.brainstormer.submit_html_plan_for_approval.blank_task_id")
    if not task_name:
        return t("tools.brainstormer.submit_html_plan_for_approval.blank_task_name")
    if not goal:
        return t("tools.brainstormer.submit_html_plan_for_approval.blank_goal")
    if not html_plan:
        return t("tools.brainstormer.submit_html_plan_for_approval.blank_html_plan")

    return t("tools.brainstormer.submit_html_plan_for_approval.output") % (
        task_id,
        task_name,
        goal,
        html_plan,
    )


BrainstormerTools = [ask_user_question, submit_html_plan_for_approval]
