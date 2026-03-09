import asyncio
from dotenv import load_dotenv

from agent.agent_v1 import AgentV1
load_dotenv() # 必須喺 import GlobalVar 前行，或者喺 GlobalVar 入面唔好即時行 os.getenv

from fastapi import FastAPI, Depends
from global_var import GlobalVar
from db.conn_pool import ConnPool, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# API Routing
from router.agent_router import router as agent_router

GlobalVar.conn_pool = ConnPool()

app = FastAPI(lifespan=GlobalVar.conn_pool.lifespan)
app.include_router(agent_router) # 註冊 API

@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    # 加強版 health check：順便試埋個 DB session 係咪真係郁到
    result = await db.execute(text("SELECT 1"))
    return {"status": "online", "database": "connected", "db_test": True}


async def main():
    target_id = "agent-9514b4d0-bd2c-4671-bf62-aea14fd8d804" 
    agent = await AgentV1.get_agent(target_id)
    
    if agent:
        print(f"✅ 成功載入 Agent: {agent.name}")
        
        # 3. 測試對話 (Streaming)
        user_msg = "Hi"
        response_gen = await agent.chat(user_msg, False)
        
        print(f"💬 {agent.name} 回應：", end="", flush=True)
        async for chunk in response_gen:
            print(chunk, end="", flush=True)
        print("\n" + "-"*100)
    else:
        print(f"❌ 搵唔到 ID 係 '{target_id}' 嘅 Agent，請先用 API 或 SQL 入一筆資料。")

    await asyncio.sleep(5)
    # 4. 關閉連線池
    await GlobalVar.conn_pool.engine.dispose()
    
if __name__ == "__main__":
    asyncio.run(main())