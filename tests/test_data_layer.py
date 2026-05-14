from datetime import datetime, timezone
from os import getenv
import re
from urllib.parse import quote_plus

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.dao import AgentDAO, LlmGroupDAO, UserAccDAO
from backend.db.base import Base
import backend.entities  # noqa: F401
from backend.dto import (
    AgentCreate,
    AgentRead,
    AgentUpdate,
    LlmGroupCreate,
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
    "long_term_mem",
    "memory_block",
    "session",
    "short_term_mem",
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
    database = getenv("POSTGRES_TEST_DB", f"{getenv('POSTGRES_DB', 'postgres')}_test")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


def assert_test_database_url(url: str) -> None:
    database = make_url(url).database or ""
    if "test" not in database.lower():
        pytest.fail(f"Database pytest must use a test DB; got database name {database!r}.")


async def ensure_test_database_exists(url: str) -> None:
    parsed_url = make_url(url)
    database = parsed_url.database or ""
    if not re.fullmatch(r"[A-Za-z0-9_]+", database):
        pytest.fail(f"Test database name must be a simple identifier; got {database!r}.")

    maintenance_db = getenv("POSTGRES_MAINTENANCE_DB", "postgres")
    maintenance_url = parsed_url.set(database=maintenance_db)
    engine = create_async_engine(maintenance_url, isolation_level="AUTOCOMMIT")

    try:
        async with engine.connect() as conn:
            exists = await conn.scalar(text("select 1 from pg_database where datname = :database"), {"database": database})
            if not exists:
                await conn.execute(text(f'create database "{database}"'))
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
        },
    )()
    assert AgentRead.model_validate(agent_obj).agent_id == "agent-1"

    assert isinstance(datetime.now(timezone.utc), datetime)


@pytest.mark.asyncio
async def test_dao_crud_happy_path():
    test_database_url = build_test_database_url()
    assert_test_database_url(test_database_url)
    await ensure_test_database_exists(test_database_url)

    engine = create_async_engine(test_database_url)
    async_session = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with async_session() as session:
            user_dao = UserAccDAO(session)
            group_dao = LlmGroupDAO(session)
            agent_dao = AgentDAO(session)

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

            updated_agent = await agent_dao.update(agent, AgentUpdate(name="Renamed Agent"))
            assert updated_agent.name == "Renamed Agent"

            await agent_dao.delete(updated_agent)
            assert await agent_dao.get_by_id(agent.id) is None
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(text("drop table if exists alembic_version"))

    await engine.dispose()
