from __future__ import annotations

from uuid import uuid4

from db.dto.agent_dto import AgentInstanceCreate, AgentInstanceUpdate


class TestAgentDtoSubAgent:
    def test_agent_instance_create_defaults_is_sub_agent_false(self):
        dto = AgentInstanceCreate(
            agent_type_id=uuid4(),
            user_id=uuid4(),
        )

        assert dto.is_sub_agent is False

    def test_agent_instance_create_accepts_is_sub_agent_true(self):
        dto = AgentInstanceCreate(
            agent_type_id=uuid4(),
            user_id=uuid4(),
            is_sub_agent=True,
        )

        assert dto.is_sub_agent is True

    def test_agent_instance_update_accepts_optional_is_sub_agent(self):
        dto = AgentInstanceUpdate(
            id=uuid4(),
            is_sub_agent=True,
        )

        assert dto.is_sub_agent is True
