#!/usr/bin/env python3
"""測試 review_stm 方法"""
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from graph.graph_store import GraphStore
from agent.bulter import Bulter
from models.llm import LLMSet
from db.dao.llm_endpoint_dao import LLMEndpointDAO
from uuid import UUID


async def test_review_stm():
    await GraphStore.init_langgraph_checkpointer()

    # Initialize the graph
    from graph.butler import workflow
    if not Bulter._graph:
        Bulter._graph = workflow.compile(checkpointer=GraphStore.checkpointer)

    # Create a Butler instance
    agent_id = "agent-6bd4f52b-8cdf-42aa-88b8-91c1a542a121"
    session_id = "default-6bd4f52b-8cdf-42aa-88b8-91c1a542a121"

    try:
        butler = await Bulter.get_agent(agent_id, session_id)
        print(f"✅ Butler instance created")
        print(f"  agent_id: {butler.agent_id}")
        print(f"  session_id: {butler.session_id}")

        # Get LLM endpoints for model_set
        endpoints = await LLMEndpointDAO.get_all_by_tenant_id(
            UUID("00000000-0000-0000-0000-000000000000")  # System tenant
        )

        if not endpoints:
            print("\n❌ No LLM endpoints found!")
            await GraphStore.pool.close()
            return

        # Create a simple model_set
        from db.dto.llm_endpoint_dto import LLMEndpoint
        model_set = LLMSet(level={}, rte_model=None)

        # Organize by routing_level
        for ep in endpoints:
            if ep.routing_level not in model_set.level:
                model_set.level[ep.routing_level] = []
            model_set.level[ep.routing_level].append(ep)

        # Set RTE model (use level 1 if available)
        if 1 in model_set.level and model_set.level[1]:
            from langchain_openai import ChatOpenAI
            from db.crypto import CryptoManager
            from pydantic import SecretStr

            first_model = model_set.level[1][0]
            api_key = CryptoManager().decrypt(first_model.api_key_encrypted) if first_model.api_key_encrypted else "EMPTY"
            model_set.rte_model = ChatOpenAI(
                base_url=first_model.base_url,
                api_key=SecretStr(api_key),
                model=first_model.model_name,
            )

        print(f"\n📊 Model set prepared:")
        print(f"  Levels: {list(model_set.level.keys())}")
        for level, models in model_set.level.items():
            print(f"  Level {level}: {len(models)} models")

        # Get state before
        config = {"configurable": {"thread_id": butler.session_id}}
        state_before = await Bulter._graph.aget_state(config)
        messages_before = state_before.values.get('messages', [])

        print(f"\n📊 BEFORE review_stm:")
        print(f"  Total messages: {len(messages_before)}")
        messages_with_id = [m for m in messages_before if hasattr(m, 'id') and m.id is not None]
        print(f"  Messages with ID: {len(messages_with_id)}")
        print(f"  Summary length: {len(state_before.values.get('summary', ''))}")

        # Execute review_stm
        print(f"\n🔄 Executing review_stm...")
        await butler.review_stm(model_set)
        print(f"  ✅ review_stm completed")

        # Get state after
        state_after = await Bulter._graph.aget_state(config)
        messages_after = state_after.values.get('messages', [])

        print(f"\n📊 AFTER review_stm:")
        print(f"  Total messages: {len(messages_after)}")
        messages_with_id_after = [m for m in messages_after if hasattr(m, 'id') and m.id is not None]
        print(f"  Messages with ID: {len(messages_with_id_after)}")
        print(f"  Summary length: {len(state_after.values.get('summary', ''))}")

        # Check results
        deleted_count = len(messages_before) - len(messages_after)
        print(f"\n📉 Messages deleted: {deleted_count}")

        if deleted_count > 0:
            print(f"  ✅ SUCCESS! review_stm deleted {deleted_count} messages")
        else:
            print(f"  ⚠️  No messages were deleted")
            print(f"     This could be normal if token count is below threshold")

        summary_before = state_before.values.get('summary', '')
        summary_after = state_after.values.get('summary', '')
        if len(summary_after) > len(summary_before):
            print(f"  ✅ Summary was updated (+{len(summary_after) - len(summary_before)} chars)")
        else:
            print(f"  ⚠️  Summary was not updated")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

    await GraphStore.pool.close()


if __name__ == '__main__':
    asyncio.run(test_review_stm())
