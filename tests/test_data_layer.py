from datetime import datetime, timezone
from os import getenv
import re
from urllib.parse import quote_plus

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.dao import (
    AgentDAO,
    AgentSessionDAO,
    LlmEndpointDAO,
    LlmGroupDAO,
    LlmLevelDAO,
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
    LlmEndpointCreate,
    LlmGroupCreate,
    LlmLevelCreate,
    LlmGroupRead,
    UserAccCreate,
    UserAccRead,
    UserAccUpdate,
)


load_dotenv()

EXPECTED_TABLES = {
    "agent",
    "agent_msg_hist",
    "llm_endpoint",
    "llm_group",
    "llm_level",
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

    session_create = AgentSessionCreate(
        recv_agent_id=1,
        session_id="session-1",
        name="Default",
        session_type="chat",
    )
    assert session_create.sender_agent_id is None

    assert isinstance(datetime.now(timezone.utc), datetime)


@pytest.mark.asyncio
async def test_dao_crud_happy_path():
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
            assert user_to_agent_runtime[-1] == "Alice"

            sender_agent = await agent_dao.create(
                AgentCreate(
                    user_id=user.id,
                    agent_id="agent-2",
                    name="Sender Agent",
                    llm_group_id=group.id,
                    agent_type="assistant",
                )
            )
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
            assert agent_to_agent_runtime[-1] == "Sender Agent"

            await session_dao.delete(user_to_agent_session)
            await session_dao.delete(agent_to_agent_session)
            await agent_dao.delete(updated_agent)
            assert await agent_dao.get_by_id(agent.id) is None
    finally:
        await engine.dispose()
        restore_metadata_schemas(original_schemas)
        await drop_test_schema(test_database_url, test_schema)
