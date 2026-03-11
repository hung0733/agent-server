import asyncio
from typing import Dict, Optional

from sqlalchemy.future import select
from agent.agent import Agent
from db.message_dao import MessageDAO
from db.agent_dao import AgentDAO
from dto.agent import AgentDTO
from dto.message import MessageDTO
from dto.session import SessionDTO
from global_var import GlobalVar
from llm.brain_agent import BrainAgent


class BackendAgent(Agent):
    """後台 Agent，每 5 分鐘 loop agent table 的 agent id"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.brain = BrainAgent(self.stream)

    @classmethod
    async def get_agent(
        cls, agent_id: str, session_id: str = "default", stream: bool = True
    ):
        agent: Optional[AgentDTO] = None
        session: Optional[SessionDTO] = None

        agent, session = await Agent.get_db_agent(agent_id, session_id)

        # 攞到資料，返傳實例
        return cls(
            db_id=agent.id,  # type: ignore
            agent_id=agent.agent_id,  # type: ignore
            session_db_id=session.id,
            session_id=session.session_id,
            name=agent.name,  # type: ignore
            sys_prompt=agent.sys_prompt,  # type: ignore
            stream=stream,
        )

async def run_backend_agents():
    """每 5 分鐘 loop agent table 的 agent id，執行後台任務"""
    while True:
        try:
            async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
                agent_dao = AgentDAO()
                agents = await agent_dao.list_all(session)

                for agent_model in agents:
                    print(f"Processing backend agent: {agent_model.agent_id}")
                    
                    # 這裡可以執行後台任務，例如：
                    # - 總結對話歷史到 long_term_memory
                    # - 清理過期的訊息
                    # - 執行定時任務
                    
                    async with GlobalVar.conn_pool.AsyncSessionLocal() as agent_session:
                        backend_agent = await BackendAgent.get_agent(agent_model.agent_id)
                        
                        # 示例：處理未鞏固的訊息到長期記憶
                        from db.long_term_memory_dao import LongTermMemoryDAO
                        ltm_dao = LongTermMemoryDAO()
                        
                        unsummarized = await ltm_dao.get_unsummarized_messages(
                            agent_session, 
                            agent_model.id
                        )
                        
                        if unsummarized:
                            print(f"Found {len(unsummarized)} unsummarized messages for agent {agent_model.agent_id}")
                            # 這裡可以調用 LLM 進行總結並儲存到 long_term_memory
                        
        except Exception as e:
            print(f"Error in backend agents loop: {e}")
        
        # 等待 5 分鐘後再次執行
        await asyncio.sleep(300)


async def start_backend_agents_loop():
    """啟動後台 Agent 循環"""
    task = asyncio.create_task(run_backend_agents())
    return task