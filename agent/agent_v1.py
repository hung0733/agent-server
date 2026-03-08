from typing import Dict

from sqlalchemy.future import select
from db.models import AgentModel
from global_var import GlobalVar
from llm.brain_agent import BrainAgent

class AgentV1:
    def __init__(self, agent_id: str, name: str, sys_prompt: str):
        self.agent_id = agent_id
        self.name = name
        self.sys_prompt = sys_prompt
        self.brain = BrainAgent()

    @classmethod
    async def get_agent(cls, agent_id: str):
        """
        喺 DB 攞資料並初始化 Agent
        """
        async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
            # 喺 DB 搵對應嘅 agent_id
            query = select(AgentModel).where(AgentModel.agent_id == agent_id)
            result = await session.execute(query)
            db_agent = result.scalars().first()

            if not db_agent:
                print(f"⚠️ Agent {agent_id} 唔存在喺資料庫。")
                return None

            # 攞到資料，返傳實例
            return cls(
                agent_id= db_agent.agent_id,
                name= db_agent.name,
                sys_prompt= db_agent.sys_prompt
            )
    
    async def chat(self, user_input: str):
        
        messages : list[Dict[str, str]] = []
        
        messages.append({"role": "system", "content": f"{self.sys_prompt}"})
        messages.append({"role": "user", "content": f"{user_input}"})
        
        print(f"🤖 Agent [{self.name}] 思考中...")
        
        response_gen = self.brain.send(messages)
        
        return response_gen