from datetime import datetime, timezone
from os import getenv
import re
from urllib.parse import quote_plus

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.client.openai import OpenAIClient
from backend.dao import (
    AgentDAO,
    AgentSessionDAO,
    AssignedTaskDAO,
    LlmEndpointDAO,
    LlmGroupDAO,
    LlmLevelDAO,
    LlmUsageDAO,
    UserAccDAO,
)
from backend.db.base import Base
from backend.llm.llm import LLMSet
import backend.entities  # noqa: F401
from backend.dto import (
    AgentCreate,
    AgentRead,
    AgentSessionCreate,
    AgentUpdate,
    AssignedTaskRead,
    AssignedTaskCreate,
    AssignedTaskStepRead,
    LlmEndpointCreate,
    LlmGroupCreate,
    LlmLevelCreate,
    LlmGroupRead,
    LlmUsageCreate,
    UserAccCreate,
    UserAccRead,
    UserAccUpdate,
)


load_dotenv()

EXPECTED_TABLES = {
    "agent",
    "agent_msg_hist",
    "agent_type",
    "assigned_task",
    "assigned_task_step",
    "assigned_task_step_process_log",
    "llm_endpoint",
    "llm_group",
    "llm_level",
    "llm_usage",
    "session",
    "user_acc",
}


def build_test_database_url() -> str:
    direct_url = getenv("TEST_DATABASE_URL") or getenv("DATABASE_TEST_URL")
    if direct_url:
        return direct_url

    host = getenv("POSTGRES_TEST_HOST", getenv("POSTGRES_HOST", "localhost"))
    port = getenv("POSTGRES_TEST_PORT", getenv("POSTGRES_PORT", "5432"))
    user = getenv("POSTGRES_TEST_USER", getenv("POSTGRES_USER", "postgres"))
    password = quote_plus(getenv("POSTGRES_TEST_PASSWORD", getenv("POSTGRES_PASSWORD", "")))
    database = getenv("POSTGRES_TEST_DB", getenv("POSTGRES_DB", "postgres"))
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


def get_test_schema() -> str:
    return getenv("TEST_SCHEMA", "test")


def assert_test_schema(schema: str) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        pytest.fail(f"TEST_SCHEMA must be a simple PostgreSQL identifier; got {schema!r}.")
    if "test" not in schema.lower():
        pytest.fail(f"TEST_SCHEMA must clearly be a test schema; got {schema!r}.")


def bind_metadata_to_schema(schema: str) -> dict[str, str | None]:
    assert_test_schema(schema)
    original_schemas = {name: table.schema for name, table in Base.metadata.tables.items()}
    for table in Base.metadata.tables.values():
        table.schema = schema
    return original_schemas


def restore_metadata_schemas(original_schemas: dict[str, str | None]) -> None:
    for name, original_schema in original_schemas.items():
        Base.metadata.tables[name].schema = original_schema


async def recreate_test_schema(url: str, schema: str) -> None:
    assert_test_schema(schema)
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")

    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'drop schema if exists "{schema}" cascade'))
            await conn.execute(text(f'create schema "{schema}"'))
    finally:
        await engine.dispose()


async def drop_test_schema(url: str, schema: str) -> None:
    assert_test_schema(schema)
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")

    try:
        async with engine.connect() as conn:
            await conn.execute(text(f'drop schema if exists "{schema}" cascade'))
    finally:
        await engine.dispose()


def test_entity_metadata_contains_expected_tables():
    assert EXPECTED_TABLES == set(Base.metadata.tables)


def test_dto_validation_and_from_attributes():
    user_create = UserAccCreate(user_id="u-1", name="Alice")
    user_update = UserAccUpdate(name="Alice Chan")
    assert user_create.phoneno is None
    assert user_update.model_dump(exclude_unset=True) == {"name": "Alice Chan"}

    user_obj = type("UserObj", (), {"id": 1, "user_id": "u-1", "name": "Alice", "phoneno": None})()
    assert UserAccRead.model_validate(user_obj).id == 1

    group_obj = type("GroupObj", (), {"id": 1, "user_id": 1, "name": "default"})()
    assert LlmGroupRead.model_validate(group_obj).name == "default"

    agent_obj = type(
        "AgentObj",
        (),
        {
            "id": 1,
            "user_id": 1,
            "agent_id": "agent-1",
            "name": "Main Agent",
            "is_active": True,
            "llm_group_id": 1,
            "agent_type": "assistant",
            "is_sub_agent": False,
            "phone_no": None,
            "whatsapp_key": None,
            "whatsapp_instance": None,
        },
    )()
    assert AgentRead.model_validate(agent_obj).agent_id == "agent-1"
    assert AgentRead.model_validate(agent_obj).whatsapp_instance is None

    assigned_task_obj = type(
        "AssignedTaskObj",
        (),
        {
            "id": 1,
            "task_id": "task_abc123",
            "user_id": 1,
            "responsible_agent_id": 1,
            "session_id": 1,
            "task_name": "Build task tracker",
            "goal": "Create root task tracking",
            "status": "brainstorm_pending",
            "approved_plan_html": None,
            "planned_task_step_json": None,
        },
    )()
    assert AssignedTaskRead.model_validate(assigned_task_obj).task_id == "task_abc123"

    assigned_task_step_obj = type(
        "AssignedTaskStepObj",
        (),
        {
            "id": 1,
            "step_id": "step_abc123",
            "task_id": 1,
            "parent_step_id": None,
            "agent_type": "brainstormer",
            "title": "Brainstorm",
            "goal": "Collect requirements",
            "status": "pending",
            "seq_no": 1,
            "assign_agent_id": 1,
            "session_id": None,
            "output_html": None,
            "output_json": None,
        },
    )()
    assert AssignedTaskStepRead.model_validate(assigned_task_step_obj).step_id == "step_abc123"

    session_create = AgentSessionCreate(
        recv_agent_id=1,
        session_id="session-1",
        name="Default",
        session_type="chat",
    )
    assert session_create.sender_agent_id is None

    assert isinstance(datetime.now(timezone.utc), datetime)


@pytest.mark.asyncio
async def test_dao_crud_happy_path(monkeypatch):
    test_database_url = build_test_database_url()
    test_schema = get_test_schema()
    await recreate_test_schema(test_database_url, test_schema)

    original_schemas = bind_metadata_to_schema(test_schema)
    engine = create_async_engine(test_database_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with async_session() as session:
            user_dao = UserAccDAO(session)
            group_dao = LlmGroupDAO(session)
            endpoint_dao = LlmEndpointDAO(session)
            level_dao = LlmLevelDAO(session)
            agent_dao = AgentDAO(session)
            session_dao = AgentSessionDAO(session)
            assigned_task_dao = AssignedTaskDAO(session)

            user = await user_dao.create(UserAccCreate(user_id="u-1", name="Alice"))
            group = await group_dao.create(LlmGroupCreate(user_id=user.id, name="default"))
            agent = await agent_dao.create(
                AgentCreate(
                    user_id=user.id,
                    agent_id="agent-1",
                    name="Main Agent",
                    llm_group_id=group.id,
                    agent_type="assistant",
                )
            )

            assert await user_dao.get_by_user_id("u-1") == user
            assert await agent_dao.get_by_agent_id("agent-1") == agent
            assert await group_dao.list_by_user_id(user.id) == [group]

            monkeypatch.setenv("LANG_LOCALE", "zh_HK")
            assigned_task = await assigned_task_dao.create(
                AssignedTaskCreate(
                    task_id="task_abc123",
                    user_id=user.id,
                    responsible_agent_id=agent.id,
                    task_name="Build task tracker",
                    goal="Create root task tracking",
                )
            )
            steps = await assigned_task_dao.create_initial_steps(
                task_db_id=assigned_task.id,
                step_ids=("step_brainstorm", "step_planning", "step_review"),
            )
            assert await assigned_task_dao.get_by_task_id("task_abc123") == assigned_task
            assert [step.step_id for step in steps] == ["step_brainstorm", "step_planning", "step_review"]
            assert [step.agent_type for step in steps] == ["brainstormer", "planner", "reviewer"]
            assert [step.assign_agent_id for step in steps] == [None, None, None]
            assert [step.status for step in steps] == ["pending", "blocked", "blocked"]
            assert [step.title for step in steps] == ["腦力激盪", "規劃", "審核"]
            assert [step.goal for step in steps] == [
                "向用戶收集需求、取得批准，並產生 HTML 計劃文件。",
                "將已批准的 HTML 計劃轉換成可執行子步驟。",
                "在開始執行前審核規劃輸出。",
            ]
            first_started_at = datetime(2026, 1, 2, 4, 0, 0, tzinfo=timezone.utc)
            second_started_at = datetime(2026, 1, 2, 5, 0, 0, tzinfo=timezone.utc)
            assert await assigned_task_dao.mark_step_processing(
                step_db_id=steps[0].id,
                now=first_started_at,
            ) is True
            await session.refresh(steps[0])
            assert steps[0].processing_started_at == first_started_at
            assert await assigned_task_dao.mark_step_processing(
                step_db_id=steps[0].id,
                now=second_started_at,
            ) is True
            await session.refresh(steps[0])
            assert steps[0].processing_started_at == first_started_at
            due_steps = await assigned_task_dao.list_due_pending_steps(
                now=second_started_at,
                limit=10,
            )
            assert [step.id for step, _agent_id in due_steps] == [steps[0].id]

            started_at = datetime.now(timezone.utc)
            process_log = await assigned_task_dao.create_process_log(
                step_db_id=steps[0].id,
                attempt_no=1,
                status="processing",
                started_at=started_at,
                finished_at=None,
                log=None,
            )
            assert process_log.finished_at is None
            assert await assigned_task_dao.count_process_logs(step_db_id=steps[0].id) == 1

            finished_at = datetime.now(timezone.utc)
            await assigned_task_dao.finish_process_log(
                process_log_db_id=process_log.id,
                status="success",
                finished_at=finished_at,
                log="done",
            )
            await session.refresh(process_log)
            assert process_log.status == "success"
            assert process_log.finished_at == finished_at
            assert process_log.log == "done"

            html_plan = "<html><body><h1>Approved plan</h1></body></html>"
            steps[0].output_html = html_plan
            await session.flush()
            assert await assigned_task_dao.approve_plan_from_step_output(
                session_db_id=steps[0].session_id,
                step_id=steps[0].step_id,
            ) is True
            await session.refresh(assigned_task)
            await session.refresh(steps[0])
            await session.refresh(steps[1])
            assert assigned_task.approved_plan_html == html_plan
            assert steps[0].status == "completed"
            assert steps[1].status == "pending"

            planner_step_session = await session_dao.create(
                AgentSessionCreate(
                    recv_agent_id=agent.id,
                    session_id="session-planner-step",
                    name="Planner Step",
                    session_type="chat",
                )
            )
            await assigned_task_dao.update_step_assignment_and_session(
                step_db_id=steps[1].id,
                session_db_id=planner_step_session.id,
            )
            planner_output_json = (
                '[{"agent_type":"engineer","title":"S1","goal":"Do work",'
                '"dependsOn":null,"status":"PENDING","seq_no":1}]'
            )
            assert await assigned_task_dao.complete_planner_step_with_planned_task_step_json(
                session_db_id=planner_step_session.id,
                planned_task_step_json=planner_output_json,
            ) is True
            await session.refresh(assigned_task)
            await session.refresh(steps[1])
            await session.refresh(steps[2])
            assert assigned_task.planned_task_step_json == planner_output_json
            assert steps[1].output_json is None
            assert steps[1].status == "completed"
            assert steps[2].status == "pending"
            assert await assigned_task_dao.complete_planner_step_with_planned_task_step_json(
                session_db_id=999999,
                planned_task_step_json="[]",
            ) is False

            assert await assigned_task_dao.approve_plan_from_step_output(
                step_id=steps[2].step_id,
            ) is False
            await session.refresh(assigned_task)
            await session.refresh(steps[2])
            assert assigned_task.approved_plan_html == html_plan
            assert steps[2].status == "pending"

            sys_endpoint = await endpoint_dao.create(
                LlmEndpointCreate(
                    user_id=None,
                    name="sys-model",
                    endpoint="http://sys.example/v1",
                    model_name="sys-model",
                )
            )
            await endpoint_dao.create(
                LlmEndpointCreate(
                    user_id=user.id,
                    name="sys-model",
                    endpoint="http://user-sys.example/v1",
                    model_name="user-sys-model",
                )
            )
            assert await endpoint_dao.list_by_sys_llm_name("sys-model") == sys_endpoint
            assert await endpoint_dao.list_by_sys_llm_name("missing") is None
            await session.commit()
            monkeypatch.setattr("backend.llm.llm.async_session_factory", async_session)
            monkeypatch.setenv("ROUTING_LLM_REC_NAME", "sys-model")
            monkeypatch.setenv("SYS_ACT_LLM_REC_NAME", "sys-model")
            assert isinstance(await LLMSet.getModelByName("sys-model"), OpenAIClient)
            assert isinstance(await LLMSet.getRteModel(), OpenAIClient)
            assert isinstance(await LLMSet.getSysActModel(), OpenAIClient)
            with pytest.raises(RuntimeError):
                await LLMSet.getModelByName("missing")

            normal_endpoint = await endpoint_dao.create(
                LlmEndpointCreate(
                    user_id=user.id,
                    name="normal",
                    endpoint="http://normal.example/v1",
                    model_name="normal-model",
                )
            )
            confidential_endpoint = await endpoint_dao.create(
                LlmEndpointCreate(
                    user_id=user.id,
                    name="confidential",
                    endpoint="http://confidential.example/v1",
                    model_name="confidential-model",
                )
            )
            await level_dao.create(
                LlmLevelCreate(
                    llm_group_id=group.id,
                    llm_endpoint_id=normal_endpoint.id,
                    level=2,
                    seq_no=1,
                )
            )
            await level_dao.create(
                LlmLevelCreate(
                    llm_group_id=group.id,
                    llm_endpoint_id=confidential_endpoint.id,
                    level=3,
                    is_confidential=True,
                    seq_no=1,
                )
            )

            levels, sec_levels = await LLMSet._load_levels(session, agent.id)
            assert [endpoint.id for endpoint in levels[2]] == [normal_endpoint.id]
            assert [endpoint.id for endpoint in sec_levels[3]] == [confidential_endpoint.id]

            usage_dao = LlmUsageDAO(session)
            usage = await usage_dao.create(
                LlmUsageCreate(
                    llm_endpoint_id=normal_endpoint.id,
                    total_token=100,
                    in_token=60,
                    cached_in_token=20,
                    out_token=40,
                )
            )
            assert usage.id is not None
            assert usage.total_token == 100
            assert usage.in_token == 60
            assert usage.cached_in_token == 20
            assert usage.out_token == 40
            all_usages = await usage_dao.list()
            assert any(u.id == usage.id for u in all_usages)

            updated_agent = await agent_dao.update(agent, AgentUpdate(name="Renamed Agent"))
            assert updated_agent.name == "Renamed Agent"

            user_to_agent_session = await session_dao.create(
                AgentSessionCreate(
                    recv_agent_id=updated_agent.id,
                    session_id="session-user-agent",
                    name="User Chat",
                    session_type="chat",
                )
            )
            user_to_agent_runtime = await session_dao.get_agent_runtime_data(
                updated_agent.agent_id,
                user_to_agent_session.session_id,
            )
            assert user_to_agent_runtime is not None
            assert user_to_agent_runtime[4] == "Alice"
            assert user_to_agent_runtime[9] is None
            assert user_to_agent_runtime[10] == "Alice"
            assert user_to_agent_runtime[11] is None
            assert user_to_agent_runtime[12] is None
            assert user_to_agent_runtime[13] is None
            assert user_to_agent_runtime[14] is False
            assert user_to_agent_runtime[15] is False

            sender_agent = await agent_dao.create(
                AgentCreate(
                    user_id=user.id,
                    agent_id="agent-2",
                    name="Sender Agent",
                    llm_group_id=group.id,
                    agent_type="assistant",
                    is_sub_agent=True,
                )
            )
            sender_default_session = await session_dao.create(
                AgentSessionCreate(
                    recv_agent_id=sender_agent.id,
                    session_id="sender-default",
                    name="Sender Default",
                    session_type="default",
                )
            )
            assert (
                await session_dao.get_default_session_by_agent_db_id(sender_agent.id)
            ) == sender_default_session

            await agent_dao.create(
                AgentCreate(
                    user_id=user.id,
                    agent_id="inactive-brainstormer",
                    name="Inactive Brainstormer",
                    llm_group_id=group.id,
                    agent_type="brainstormer",
                    is_active=False,
                    is_sub_agent=True,
                )
            )
            await agent_dao.create(
                AgentCreate(
                    user_id=user.id,
                    agent_id="non-sub-brainstormer",
                    name="Non Sub Brainstormer",
                    llm_group_id=group.id,
                    agent_type="brainstormer",
                    is_sub_agent=False,
                )
            )
            assigned_brainstormer = await agent_dao.create(
                AgentCreate(
                    user_id=user.id,
                    agent_id="assigned-brainstormer",
                    name="Assigned Brainstormer",
                    llm_group_id=group.id,
                    agent_type="brainstormer",
                    is_sub_agent=True,
                )
            )
            later_brainstormer = await agent_dao.create(
                AgentCreate(
                    user_id=user.id,
                    agent_id="later-brainstormer",
                    name="Later Brainstormer",
                    llm_group_id=group.id,
                    agent_type="brainstormer",
                    is_sub_agent=True,
                )
            )
            assert (
                await agent_dao.get_first_active_sub_agent_by_user_and_type(
                    user_id=user.id,
                    agent_type_id=steps[0].agent_type_id,
                )
            ) == assigned_brainstormer
            assert later_brainstormer.id > assigned_brainstormer.id

            await assigned_task_dao.update_task_session(
                task_db_id=assigned_task.id,
                session_db_id=sender_default_session.id,
            )
            await assigned_task_dao.update_step_assignment_and_session(
                step_db_id=steps[0].id,
                assign_agent_db_id=assigned_brainstormer.id,
                session_db_id=sender_default_session.id,
            )
            await session.refresh(assigned_task)
            await session.refresh(steps[0])
            assert assigned_task.session_id == sender_default_session.id
            assert steps[0].assign_agent_id == assigned_brainstormer.id
            assert steps[0].session_id == sender_default_session.id

            agent_to_agent_session = await session_dao.create(
                AgentSessionCreate(
                    recv_agent_id=updated_agent.id,
                    session_id="session-agent-agent",
                    name="Agent Chat",
                    session_type="chat",
                    sender_agent_id=sender_agent.id,
                )
            )
            agent_to_agent_runtime = await session_dao.get_agent_runtime_data(
                updated_agent.agent_id,
                agent_to_agent_session.session_id,
            )
            assert agent_to_agent_runtime is not None
            assert agent_to_agent_runtime[4] == "Alice"
            assert agent_to_agent_runtime[9] == sender_agent.agent_id
            assert agent_to_agent_runtime[10] == "Sender Agent"
            assert agent_to_agent_runtime[11] == sender_agent.id
            assert agent_to_agent_runtime[12] == sender_default_session.id
            assert agent_to_agent_runtime[13] == sender_default_session.session_id
            assert agent_to_agent_runtime[14] is True
            assert agent_to_agent_runtime[15] is False

            await session.delete(process_log)
            await assigned_task_dao.delete(assigned_task)
            await session_dao.delete(planner_step_session)
            await session_dao.delete(user_to_agent_session)
            await session_dao.delete(agent_to_agent_session)
            await session_dao.delete(sender_default_session)
            await agent_dao.delete(updated_agent)
            assert await agent_dao.get_by_id(agent.id) is None
    finally:
        await engine.dispose()
        restore_metadata_schemas(original_schemas)
        await drop_test_schema(test_database_url, test_schema)
