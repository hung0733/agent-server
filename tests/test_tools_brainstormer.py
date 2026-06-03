import pytest

from backend.i18n import t
from backend.tools.brainstormer import (
    ask_user_question,
    submit_html_plan_for_approval,
)


def test_ask_user_question_schema_exposes_only_expected_arguments():
    schema = ask_user_question.args_schema.model_json_schema()

    assert ask_user_question.description == t(
        "tools.brainstormer.ask_user_question.description"
    )
    assert set(schema["properties"]) == {"question", "description", "choose"}
    assert schema["required"] == ["question", "description", "choose"]
    assert "runtime" not in schema["properties"]
    assert (
        schema["properties"]["question"]["description"]
        == t("tools.brainstormer.ask_user_question.question.description")
    )
    assert (
        schema["properties"]["description"]["description"]
        == t("tools.brainstormer.ask_user_question.description.description")
    )
    assert (
        schema["properties"]["choose"]["description"]
        == t("tools.brainstormer.ask_user_question.choose.description")
    )


def test_submit_html_plan_for_approval_schema_exposes_only_expected_arguments():
    schema = submit_html_plan_for_approval.args_schema.model_json_schema()

    assert submit_html_plan_for_approval.description == t(
        "tools.brainstormer.submit_html_plan_for_approval.description"
    )
    assert set(schema["properties"]) == {
        "task_id",
        "task_name",
        "goal",
        "html_plan",
    }
    assert schema["required"] == ["task_id", "task_name", "goal", "html_plan"]
    assert "runtime" not in schema["properties"]


@pytest.mark.asyncio
async def test_ask_user_question_rejects_blank_inputs():
    assert (
        await ask_user_question.coroutine(" ", "說明", ["A"])
        == t("tools.brainstormer.ask_user_question.blank_question")
    )
    assert (
        await ask_user_question.coroutine("問題", " ", ["A"])
        == t("tools.brainstormer.ask_user_question.blank_description")
    )
    assert (
        await ask_user_question.coroutine("問題", "說明", [" ", ""])
        == t("tools.brainstormer.ask_user_question.blank_choose")
    )


@pytest.mark.asyncio
async def test_ask_user_question_returns_numbered_choices():
    result = await ask_user_question.coroutine(
        " 你想優先做邊個方向？ ",
        " 用戶需要先揀方向，Planner 才能拆步驟。 ",
        [" 產品 MVP ", "", " 品牌定位 "],
    )

    assert "你想優先做邊個方向？" in result
    assert "用戶需要先揀方向" in result
    assert "1. 產品 MVP" in result
    assert "2. 品牌定位" in result


@pytest.mark.asyncio
async def test_submit_html_plan_for_approval_rejects_blank_inputs():
    assert (
        await submit_html_plan_for_approval.coroutine(
            " ", "任務", "目標", "<section>Plan</section>"
        )
        == t("tools.brainstormer.submit_html_plan_for_approval.blank_task_id")
    )
    assert (
        await submit_html_plan_for_approval.coroutine(
            "task-1", " ", "目標", "<section>Plan</section>"
        )
        == t("tools.brainstormer.submit_html_plan_for_approval.blank_task_name")
    )
    assert (
        await submit_html_plan_for_approval.coroutine(
            "task-1", "任務", " ", "<section>Plan</section>"
        )
        == t("tools.brainstormer.submit_html_plan_for_approval.blank_goal")
    )
    assert (
        await submit_html_plan_for_approval.coroutine("task-1", "任務", "目標", " ")
        == t("tools.brainstormer.submit_html_plan_for_approval.blank_html_plan")
    )


@pytest.mark.asyncio
async def test_submit_html_plan_for_approval_returns_plan_content():
    html_plan = "<section><h1>Plan</h1><p>Step 1</p></section>"

    result = await submit_html_plan_for_approval.coroutine(
        " task-1 ",
        " 打卡網站 ",
        " 建立可以審批的 MVP 計劃 ",
        html_plan,
    )

    assert "task-1" in result
    assert "打卡網站" in result
    assert "建立可以審批的 MVP 計劃" in result
    assert html_plan in result
