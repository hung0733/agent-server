import asyncio
import sys
from dotenv import load_dotenv

from dto.message import MessageDTO

load_dotenv()  # 必須喺 import GlobalVar 前行，或者喺 GlobalVar 入面唔好即時行 os.getenv

from fastapi import FastAPI, Depends
from global_var import GlobalVar
from db.conn_pool import ConnPool, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

# API Routing
from router.agent_router import router as agent_router
from agent.backend_agent import start_backend_agents_loop
from router.chat_router import router as chat_router
from router.session_router import router as session_router
from router.message_router import router as message_router

GlobalVar.conn_pool = ConnPool()

app = FastAPI(lifespan=GlobalVar.conn_pool.lifespan)
app.include_router(agent_router, prefix="/v1")  # 註冊 Agent API
app.include_router(chat_router, prefix="/v1")  # 註冊 OpenAI Chat API
app.include_router(session_router, prefix="/v1")  # 註冊 Session API
app.include_router(message_router, prefix="/v1")  # 註冊 Message API


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    # 加強版 health check：順便試埋個 DB session 係咪真係郁到
    result = await db.execute(text("SELECT 1"))
    return {"status": "online", "database": "connected", "db_test": True}


async def run_with_backend():
    """運行 FastAPI 服務器 + 後台 Agent"""
    import uvicorn
    
    # 啟動後台 Agent 循環（每 5 分鐘 loop agent table）
    backend_task = await start_backend_agents_loop()
    
    # 啟動 FastAPI 服務器
    config = uvicorn.Config(app, host="0.0.0.0", port=8600)
    server = uvicorn.Server(config)
    
    # 同時運行服務器和後台任務
    await asyncio.gather(
        server.serve(),
        backend_task
    )

if __name__ == "__main__":
    asyncio.run(run_with_backend())
