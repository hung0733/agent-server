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


async def main():
    from agent.agent_v1 import AgentV1

    target_id = "agent-9514b4d0-bd2c-4671-bf62-aea14fd8d804"
    agent = await AgentV1.get_agent(target_id)

    if not agent:
        print(f"❌ 搵唔到 ID 係 '{target_id}' 嘅 Agent。")
        return

    print(f"✅ 成功載入 Agent: {agent.name}")
    print("--- 已進入對話模式 (輸入 'exit' 或 'quit' 退出) ---")

    while True:
        await ConnPool.wait_task_comp()

        # 1. 獲取用戶輸入
        print("\n👤 你 (多行輸入): ")
        user_msg = sys.stdin.read().strip()  # 呢度會等 Ctrl+D

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
        print("\n" + "-" * 100)

    await GlobalVar.conn_pool.dispose()


async def test_summary():

    async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
        from db.models import MessageModel

        query = select(MessageModel).order_by(MessageModel.create_date.asc())
        result = await session.execute(query)
        historys: list[MessageDTO] = [
            MessageDTO.get(m) for m in (result.scalars().all() or [])
        ]
        
        summary_cont : str = ""
        for msg in historys:
            summary_cont += msg.date.strftime("%Y-%m-%d %H:%M:%S") + "\n"
            summary_cont += msg.sent_by + ":\n"
            summary_cont += msg.content + "\n\n"
        
        print(f"Summary Content:")
        print("\n" + "-" * 100)
        print(summary_cont)
        print("\n" + "-" * 100)
    
    from llm.summary_agent import SummaryAgent
    client: SummaryAgent = SummaryAgent()
    
    sys_prompt : str = """
請嚴格遵守 [Universal Multi-Topic Summary Prompt] 協議：

1. [日期] 標註於最上方。

2. 若對話包含多個互不相關的主題，必須使用 ### [Topic Name] 進行分塊摘要。

3. 每個主題區塊需包含：該主題的核心事件、引號包裹的關鍵事實、技術參數、以及該項目的最終狀態。

4. 絕對禁止將不同主題的關鍵事實（如秘密代碼與旅遊景點）混寫在同一個段落。

5. 保持資訊密度，禁止輸出 Source Code。
"""
    
    print(sys_prompt)
    print("\n" + "-" * 100)
    
    gen = client.send(sys_prompt, summary_cont, False)
            
    if hasattr(gen, '__iter__'):
        for chunk in gen:
            print(chunk, end="", flush=True)
    else:
        print(gen, end="", flush=True)
    
    print("\n" + "-" * 100)

    await GlobalVar.conn_pool.dispose()


if __name__ == "__main__":
    # 運行 FastAPI 服務器
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8600)
