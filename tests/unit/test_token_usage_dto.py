from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from db.dto.token_usage_dto import TokenUsageCreate


def test_token_usage_create_accepts_nullable_task_and_endpoint_links() -> None:
    dto = TokenUsageCreate(
        user_id=uuid4(),
        agent_id=uuid4(),
        session_id="session-123",
        model_name="qwen3.5-35b-a3b",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        estimated_cost_usd=Decimal("0"),
        task_id=None,
        llm_endpoint_id=None,
    )

    assert dto.task_id is None
    assert dto.llm_endpoint_id is None
