from contextlib import asynccontextmanager
import os
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

class ConnPool:
    def __init__(self) -> None:
        # 資料庫連線設定 (參考 pgsql.yml 嘅設定)
        # 格式: postgresql+asyncpg://user:password@host:port/dbname
        db_user : str = os.getenv("DB_USER", "")
        db_pass : str = os.getenv("DB_PASSWORD", "") # 根據 pgsql.yml
        db_host : str = os.getenv("DB_HOST", "")
        db_port : str = os.getenv("DB_PORT", "")
        db_name : str = os.getenv("DB_NAME", "")

        db_endpoint : str = f"postgresql+asyncpg://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        
        # 1. 建立 Async Engine
        # pool_size: 連線池大細
        # max_overflow: 超出 pool_size 後最多可額外開幾多個連線
        self.engine = create_async_engine(
            db_endpoint,
            echo=False, # 如果要 debug SQL 可以轉做 True
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True # 每次攞連線前檢查係咪仲有用，防止 stale connection
        )

        # 2. 建立 Session 工廠
        self.AsyncSessionLocal = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    # Dependency Injection: 俾其他 API Route 攞 DB Session 用
    async def get_db(self):
        async with self.AsyncSessionLocal() as session:
            try:
                yield session
            finally:
                await session.close()
        
    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        # Startup: 驗證 DB 連線
        try:
            async with self.engine.begin() as conn:
                # 簡單行一個 SELECT 1 嚟試吓個 Pool 郁唔郁到
                from sqlalchemy import text
                await conn.execute(text("SELECT 1"))
            print("✅ Database connection pool initialized successfully.")
        except Exception as e:
            print(f"❌ Failed to initialize database pool: {e}")
            raise e
            
        yield
        
        # Shutdown: 釋放資源
        await self.engine.dispose()
        print("🛑 Database connection pool closed.")