#!/usr/bin/env python3
"""
Debug script to check agent_messages table and understand why records are not found.

Usage:
    python scripts/debug_agent_messages.py
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# Load environment variables from .env
from dotenv import load_dotenv
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)

from db.dao.agent_message_dao import AgentMessageDAO
from db.dao.collaboration_session_dao import CollaborationSessionDAO
from db.dao.agent_instance_dao import AgentInstanceDAO
from sqlalchemy import select, func
from db import create_engine, async_sessionmaker, AsyncSession
from db.entity.collaboration_entity import AgentMessage as AgentMessageEntity
from db.entity.collaboration_entity import CollaborationSession as CollaborationSessionEntity
from db.entity.agent_entity import AgentInstance as AgentInstanceEntity


async def main():
    """Debug agent_messages table."""
    print("🔍 開始 Debug agent_messages 表...\n")

    engine = create_engine()
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 1. Count total agent_messages
        print("1️⃣ 統計 agent_messages 總數...")
        result = await session.execute(
            select(func.count()).select_from(AgentMessageEntity)
        )
        total_count = result.scalar() or 0
        print(f"   ✅ 總共有 {total_count} 條 agent_messages 記錄\n")

        # 2. Count by is_summarized
        print("2️⃣ 統計 is_summarized 狀態...")
        result = await session.execute(
            select(
                AgentMessageEntity.is_summarized,
                func.count(AgentMessageEntity.id)
            )
            .group_by(AgentMessageEntity.is_summarized)
        )
        for is_summarized, count in result.all():
            print(f"   is_summarized = {is_summarized}: {count} 條記錄")
        print()

        # 3. Check collaboration_sessions
        print("3️⃣ 檢查 collaboration_sessions...")
        result = await session.execute(
            select(func.count()).select_from(CollaborationSessionEntity)
        )
        collab_count = result.scalar() or 0
        print(f"   ✅ 總共有 {collab_count} 條 collaboration_sessions 記錄\n")

        # 4. Check session_id prefixes
        print("4️⃣ 統計 session_id 前綴...")
        result = await session.execute(
            select(CollaborationSessionEntity.session_id)
        )
        session_ids = [row[0] for row in result.all()]

        prefixes = {}
        for sid in session_ids:
            prefix = sid.split('-')[0] if '-' in sid else 'other'
            prefixes[prefix] = prefixes.get(prefix, 0) + 1

        for prefix, count in sorted(prefixes.items()):
            print(f"   {prefix}-*: {count} 個 sessions")
        print()

        # 5. Check agent_instances
        print("5️⃣ 檢查 agent_instances...")
        result = await session.execute(
            select(AgentInstanceEntity.id, AgentInstanceEntity.agent_id)
        )
        agents = result.all()
        print(f"   ✅ 總共有 {len(agents)} 個 agent instances")
        for agent_uuid, agent_id_str in agents[:5]:  # Show first 5
            print(f"      - UUID: {agent_uuid}, agent_id: {agent_id_str}")
        print()

        # 6. Check JOIN result
        print("6️⃣ 測試 JOIN 查詢（agent_messages → collaboration_sessions → agent_instances）...")
        result = await session.execute(
            select(
                func.count()
            )
            .select_from(AgentMessageEntity)
            .join(
                CollaborationSessionEntity,
                AgentMessageEntity.collaboration_id == CollaborationSessionEntity.id
            )
            .join(
                AgentInstanceEntity,
                CollaborationSessionEntity.main_agent_id == AgentInstanceEntity.id
            )
        )
        join_count = result.scalar() or 0
        print(f"   ✅ JOIN 結果：{join_count} 條記錄")

        if join_count == 0:
            print("   ⚠️  JOIN 結果為 0！可能原因：")
            print("      1. agent_messages.collaboration_id 沒有對應的 collaboration_sessions")
            print("      2. collaboration_sessions.main_agent_id 沒有對應的 agent_instances")
        print()

        # 7. Check orphaned agent_messages
        print("7️⃣ 檢查沒有對應 collaboration_session 的 agent_messages...")
        result = await session.execute(
            select(func.count())
            .select_from(AgentMessageEntity)
            .outerjoin(
                CollaborationSessionEntity,
                AgentMessageEntity.collaboration_id == CollaborationSessionEntity.id
            )
            .where(CollaborationSessionEntity.id.is_(None))
        )
        orphaned_count = result.scalar() or 0
        print(f"   ⚠️  有 {orphaned_count} 條 agent_messages 沒有對應的 collaboration_session\n")

        # 8. Sample some agent_messages
        print("8️⃣ 查看前 5 條 agent_messages...")
        result = await session.execute(
            select(AgentMessageEntity)
            .order_by(AgentMessageEntity.created_at.desc())
            .limit(5)
        )
        messages = result.scalars().all()

        for i, msg in enumerate(messages, 1):
            print(f"\n   Message #{i}:")
            print(f"      ID: {msg.id}")
            print(f"      collaboration_id: {msg.collaboration_id}")
            print(f"      is_summarized: {msg.is_summarized}")
            print(f"      is_analyzed: {msg.is_analyzed}")
            print(f"      created_at: {msg.created_at}")

            # Try to find the collaboration_session
            collab_result = await session.execute(
                select(CollaborationSessionEntity)
                .where(CollaborationSessionEntity.id == msg.collaboration_id)
            )
            collab = collab_result.scalar_one_or_none()

            if collab:
                print(f"      ✅ collaboration_session 存在:")
                print(f"         session_id: {collab.session_id}")
                print(f"         main_agent_id: {collab.main_agent_id}")

                # Try to find the agent_instance
                agent_result = await session.execute(
                    select(AgentInstanceEntity)
                    .where(AgentInstanceEntity.id == collab.main_agent_id)
                )
                agent = agent_result.scalar_one_or_none()

                if agent:
                    print(f"         ✅ agent_instance 存在: {agent.agent_id}")
                else:
                    print(f"         ❌ agent_instance 不存在！")
            else:
                print(f"      ❌ collaboration_session 不存在！")

        # 9. Test the actual query with a specific agent_id
        print("\n\n9️⃣ 測試實際查詢（使用第一個 agent）...")
        if agents:
            test_agent_id = agents[0][1]  # agent_id string
            print(f"   使用 agent_id: {test_agent_id}")

            # Use the actual DAO method
            now_utc = datetime.now(timezone.utc)
            start_of_today = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

            grouped = await AgentMessageDAO.get_unsummarized_messages_grouped(
                agent_id=test_agent_id,
                before_date=start_of_today,
                session=session
            )

            if grouped:
                total_messages = sum(
                    len(messages)
                    for session_groups in grouped.values()
                    for messages in session_groups.values()
                )
                print(f"   ✅ 找到 {len(grouped)} 個日期，共 {total_messages} 條訊息")
                for date_str, session_groups in list(grouped.items())[:3]:
                    print(f"      {date_str}: {len(session_groups)} 個 sessions")
            else:
                print(f"   ❌ 沒有找到記錄")
                print(f"   🔍 可能原因：")
                print(f"      - is_summarized 都是 True")
                print(f"      - created_at >= {start_of_today}")
                print(f"      - session_id 不是以 'agent-' 或 'session-' 開頭")

    await engine.dispose()
    print("\n✅ Debug 完成！")


if __name__ == "__main__":
    asyncio.run(main())
