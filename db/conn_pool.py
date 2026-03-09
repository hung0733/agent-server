from contextlib import asynccontextmanager
import os
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

class ConnPool:
    pending_tasks = set()
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
        
    @asynccontextmanager
    async def lifespan(self, app: FastAPI):
        # Startup
        try:
            async with self.engine.begin() as conn:
                from sqlalchemy import text
                await conn.execute(text("SELECT 1"))
            print("✅ Database connection pool initialized.")
        except Exception as e:
            print(f"❌ DB initialization failed: {e}")
            raise e
            
        yield # 呢度係 API 行緊嘅時間
        
        # Shutdown
        await self.engine.dispose()
        print("🛑 Database connection pool closed.")
        
    async def dispose(self):
        await self.wait_task_comp()
        await self.engine.dispose()
    
    @staticmethod
    async def wait_task_comp():
        if ConnPool.pending_tasks:
            import asyncio
            print(f"⏳ 正在等待 {len(ConnPool.pending_tasks)} 個儲存任務...")
            await asyncio.gather(*ConnPool.pending_tasks)

# Dependency Injection: 俾其他 API Route 攞 DB Session 用
async def get_db():
    from global_var import GlobalVar
    async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()