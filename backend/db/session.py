from collections.abc import AsyncIterator
from os import getenv
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


load_dotenv()


def build_database_url() -> str:
    direct_url = getenv("DATABASE_URL")
    if direct_url:
        return direct_url

    host = getenv("POSTGRES_HOST", "localhost")
    port = getenv("POSTGRES_PORT", "5432")
    user = getenv("POSTGRES_USER", "postgres")
    password = quote_plus(getenv("POSTGRES_PASSWORD", ""))
    database = getenv("POSTGRES_DB", "postgres")
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{database}"


def create_async_engine_from_env():
    return create_async_engine(build_database_url(), pool_pre_ping=True)


engine = create_async_engine_from_env()
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
