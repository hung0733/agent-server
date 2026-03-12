import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from agent.agent import Agent
from agent.archive_ghost import ArchiveGhost
from db.agent_dao import AgentDAO
from db.message_dao import MessageDAO
from db.session_dao import SessionDAO
from dto.agent import AgentDTO
from dto.message import MessageDTO
from global_var import GlobalVar

# 全局鎖，確保同一時間只有一個 run_backend_agents 實例在運行
_global_lock = asyncio.Lock()


async def run_backend_agents():
    """每小時執行一次後台任務

    執行時間：每小時的 0 分
    同一時間只能有 1 個實例在運行（通過全局鎖機制確保）
    """
    while True:
        try:
            # 等待到下一個整點
            current_time = datetime.now()

            # 計算距離下一個整點還需要等待的時間
            minute = current_time.minute
            second = current_time.second
            microsecond = current_time.microsecond

            # 計算需要等待的秒數
            wait_seconds = (60 - minute) * 60 - second
            wait_microseconds = -microsecond

            print(
                f"Current time: {current_time}, waiting for {60 - minute} minutes until next hour"
            )

            # 等待到下一個整點
            await asyncio.sleep(wait_seconds + wait_microseconds / 1000000)

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
                    await init_agent_task(agent_dto)
                    await summary_distillation_task(agent_dto)

                print("Backend agents task completed")

        except Exception as e:
            print(f"Error in backend agents loop: {e}")


async def start_backend_agents_loop():
    """啟動後台 Agent 循環

    1. 程式啟動時無條件執行一次
    2. 之後每小時執行一次
    """
    # 程式啟動時先執行一次
    print("Starting backend agents task at program startup")
    await run_backend_agents_once()

    # 之後每小時執行一次
    task = asyncio.create_task(run_backend_agents())
    return task


async def run_backend_agents_once():
    """執行一次後台任務（不進行循環）"""
    try:
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
                await init_agent_task(agent_dto)
                await summary_distillation_task(agent_dto)

            print("Backend agents task completed")

    except Exception as e:
        print(f"Error in backend agents task: {e}")


async def init_agent_task(agent_dto: AgentDTO):
    if agent_dto.is_inited:
        return

    session_id: str = "init_agent-" + datetime.now().strftime("%Y%m%m")
    async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
        await SessionDAO().make_sure_exist(
            session=session, agent_db_id=agent_dto.id, session_id=session_id
        )

    agent: ArchiveGhost | None = await ArchiveGhost.get_agent(
        agent_id=agent_dto.agent_id, session_id=session_id
    )

    print(f"Start Init Agent: {agent_dto.agent_id}")
    await agent.init_agent()


async def summary_distillation_task(agent_dto: AgentDTO):

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
        agent: ArchiveGhost | None = await ArchiveGhost.get_agent(
            agent_id=agent_dto.agent_id, session_id=session_id
        )
        if agent:
            for e in grouped_messages:
                target_session_id: str = e["session_id"]
                date: str = e["date"]
                messages: List[MessageDTO] = e["messages"]
                print(f"Start Summary Message: {date} {target_session_id}")
                await agent.summary(messages)
                print(f"Start Reflection & Distillation: {date} {target_session_id}")
                await agent.distillation(messages)
