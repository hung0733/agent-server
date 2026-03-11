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
        valid_count = 0
        for msg in historys:
            if (msg.msg_type in ["user_message", "assistant_message"]):
                summary_cont += msg.date.strftime("%Y-%m-%d %H:%M:%S") + "\n"
                summary_cont += msg.sent_by + ":\n"
                summary_cont += msg.content + "\n\n"
                valid_count += 1
    
    

    sys_prompt : str = """
**Role**: 你是一個具備語言感知能力的高密度數據提取引擎，專門為「向量資料庫 (Vector DB)」準備 RAG 記憶存檔。

**Task**: 請將對話內容拆解並轉換為多個獨立的「原子化 Record」 JSON 物件。

**Output Format**: 僅輸出一個包含 JSON List 的物件，嚴禁任何解釋性文字。

**Language Constraint (語言約束)**:
1. **語體一致**: JSON 內的所有文字欄位（topic, event_summary, critical_facts）必須「嚴格遵循原始對話的語言與語氣」。
2. **廣東話保留**: 若原始對話使用廣東話（如：小丸風格），摘要必須保留廣東話關鍵詞與語法，不得擅自轉為書面語或英文。
3. **實體不變**: 專有名詞、代碼、密鑰必須 100% 保持原始格式。

**JSON Structure**:
{
  "records": [
    {
      "record_id": "對話雜湊或序號",
      "timestamp_range": {
        "start": "YYYY-MM-DD HH:MM:SS",
        "end": "YYYY-MM-DD HH:MM:SS"
      },
      "topic": "主題名稱（用對話語言撰寫）",
      "event_summary": "核心事件描述（用對話語言撰寫，一句話總結）",
      "critical_facts": ["原始數據或語句（如：『抹茶味小籠包』）"],
      "technical_index": {
        "logic": "實作的功能描述（嚴禁輸出源碼）",
        "params": ["具體數值", "方法名稱", "價格"]
      },
      "status": "Archived / Success / Pending"
    }
  ]
}

**Strict Constraints**:
- 禁止輸出任何 JSON 以外的解釋。
- 主題必須完全隔離，不同事件拆分不同 Record。
- 確保 `timestamp_range` 反映該話題在對話中出現的實際時間段。
"""
    
    # print(sys_prompt)
    # print("\n" + "-" * 100)
    # print(sys_prompt_2)
    # print("\n" + "-" * 100)

    
    from llm.summary_agent import SummaryAgent
    client: SummaryAgent = SummaryAgent()
    gen = client.send(sys_prompt, summary_cont, False)

    async for chunk in gen:
        if hasattr(chunk, 'choices') and chunk.choices:
            choice = chunk.choices[0]
            if hasattr(choice, 'delta') and choice.delta:
                reasoning = getattr(choice.delta, 'reasoning_content', None)
                if reasoning:
                    print(reasoning, end="", flush=True)
                content = choice.delta.content
                if content:
                    print(content, end="", flush=True)

    # print("\n" + "-" * 100)

    await GlobalVar.conn_pool.dispose()


if __name__ == "__main__":
    asyncio.run(test_summary())
    # # 運行 FastAPI 服務器
    # import uvicorn
    # uvicorn.run(app, host="0.0.0.0", port=8600)
