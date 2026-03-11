import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from agent.agent import Agent
from agent.backend_agent import BackendAgent
from db.agent_dao import AgentDAO
from db.message_dao import MessageDAO
from db.session_dao import SessionDAO
from dto.agent import AgentDTO
from dto.message import MessageDTO
from global_var import GlobalVar

# 全局鎖，確保同一時間只有一個 run_backend_agents 實例在運行
_global_lock = asyncio.Lock()


async def run_backend_agents():
    """每 5 分鐘 loop agent table 的 agent id，執行後台任務

    執行時間：每小時的 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55 分
    同一時間只能有 1 個實例在運行（通過全局鎖機制確保）
    """
    while True:
        try:
            # 等待到下一個 5 分鐘標記
            current_time = datetime.now()

            # 計算距離下一個 5 分鐘標記還需要等待的時間
            minute = current_time.minute
            seconds = current_time.second

            # 找出下一個要執行的 5 分鐘標記（5, 10, 15, ...）
            next_marker = ((minute // 5) + 1) * 5

            # 如果當前分數已經是 5 的倍數，則等待到下一輪
            if minute % 5 == 0 and seconds == 0:
                wait_minutes = 5
            else:
                wait_minutes = next_marker - minute

            # 計算需要等待的秒數（包括當前的秒數）
            wait_seconds = (wait_minutes * 60) - seconds

            print(
                f"Current time: {current_time}, waiting for {wait_minutes} minutes until minute {next_marker}"
            )

            # 等待到下一個 5 分鐘標記
            await asyncio.sleep(wait_seconds)

            # 使用全局鎖確保同一時間只有一個實例在運行
            async with _global_lock:
                print(
                    f"Acquired global lock at {datetime.now()}, starting backend agents task"
                )

                agents: list[AgentDTO] = []
                # 執行後台任務
                async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
                    agent_dao = AgentDAO()
                    agents = [
                        AgentDTO.from_model(agent_model)
                        for agent_model in await agent_dao.list_all(session) or []
                    ]

                for agent_dto in agents:
                    print(f"Processing backend agent: {agent_dto.agent_id}")
                    await summary_task(agent_dto)

                print("Backend agents task completed")

        except Exception as e:
            print(f"Error in backend agents loop: {e}")


async def start_backend_agents_loop():
    """啟動後台 Agent 循環"""
    task = asyncio.create_task(run_backend_agents())
    return task


async def summary_task(agent_dto: AgentDTO):

    grouped_messages: List[Dict[str, Any]] = []
    session_id: str = "summary-" + datetime.now().strftime("%Y%m%m")

    print(f"Try Find {agent_dto.agent_id} non summary Messages")
    async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
        grouped_messages = await MessageDAO().list_grouped_before_today(
            session=session, agent_db_id=agent_dto.id
        )
        if grouped_messages:
            await SessionDAO().make_sure_exist(
                session=session, agent_db_id=agent_dto.id, session_id=session_id
            )

    if grouped_messages:
        agent: BackendAgent = await BackendAgent.get_agent(
            agent_id=agent_dto.agent_id, session_id=session_id
        )
        if agent:
            for e in grouped_messages:
                target_session_id: str = e["session_id"]
                date: str = e["date"]
                messages: List[MessageDTO] = e["messages"]
                print(f"Start Summary Message: {date} {target_session_id}")
                await agent.summary(messages)
