
import asyncio
from datetime import datetime

from db.agent_dao import AgentDAO
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
            
            print(f"Current time: {current_time}, waiting for {wait_minutes} minutes until minute {next_marker}")
            
            # 等待到下一個 5 分鐘標記
            await asyncio.sleep(wait_seconds)
            
            # 使用全局鎖確保同一時間只有一個實例在運行
            async with _global_lock:
                print(f"Acquired global lock at {datetime.now()}, starting backend agents task")
                
                # 執行後台任務
                async with GlobalVar.conn_pool.AsyncSessionLocal() as session:
                    agent_dao = AgentDAO()
                    agents = await agent_dao.list_all(session)

                    for agent_model in agents:
                        print(f"Processing backend agent: {agent_model.agent_id}")
                        
                        # 這裡可以執行後台任務，例如：
                        # - 總結對話歷史到 long_term_memory
                        # - 清理過期的訊息
                        # - 執行定時任務
                        
                        
                    
                    print("Backend agents task completed")
        
        except Exception as e:
            print(f"Error in backend agents loop: {e}")


async def start_backend_agents_loop():
    """啟動後台 Agent 循環"""
    task = asyncio.create_task(run_backend_agents())
    return task