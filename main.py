import asyncio
import sys
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
    
    if not agent:
        print(f"❌ 搵唔到 ID 係 '{target_id}' 嘅 Agent。")
        return

    print(f"✅ 成功載入 Agent: {agent.name}")
    print("--- 已進入對話模式 (輸入 'exit' 或 'quit' 退出) ---")

    while True:
        await GlobalVar.conn_pool.wait_task_comp()
        
        # 1. 獲取用戶輸入
        print("\n👤 你 (多行輸入): ")
        user_msg = sys.stdin.read().strip() # 呢度會等 Ctrl+D
        
        if user_msg.lower() in ["exit", "quit", "離開"]:
            print("🛑 對話結束。")
            break
            
        if not user_msg:
            continue
            
        # 2. 呼叫 Agent Chat (Async Generator)
        response_gen_func = await agent.chat(user_msg, False)
        
        print(f"💬 {agent.name}: ", end="", flush=True)
        
        # 3. 處理 Streaming 輸出
        async for chunk in response_gen_func:
            print(chunk, end="", flush=True)
        print("\n" + "-"*50)
    
    await GlobalVar.conn_pool.dispose()  
    
async def test_summary():
    
    await GlobalVar.conn_pool.dispose()  
    
if __name__ == "__main__":
    # asyncio.run(main())
    asyncio.run(test_summary())