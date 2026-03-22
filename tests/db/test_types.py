# pyright: reportMissingImports=false
"""
Tests for database types and enums.

This module tests all enum types and base model functionality
to ensure proper serialization, deserialization, and behavior.
"""
import json
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import BaseModel

from db.types import (
    AgentStatus,
    DependencyType,
    Priority,
    TaskStatus,
    gen_random_uuid,
)
from db.models.base import BaseModelWithID, now_utc


class TestAgentStatus:
    """Tests for AgentStatus enum."""

    def test_enum_values(self):
        """Test that all enum variants have correct string values."""
        assert AgentStatus.idle == "idle"
        assert AgentStatus.busy == "busy"
        assert AgentStatus.error == "error"
        assert AgentStatus.offline == "offline"

    def test_enum_membership(self):
        """Test that all variants are in the enum."""
        assert AgentStatus("idle") is AgentStatus.idle
        assert AgentStatus("busy") is AgentStatus.busy
        assert AgentStatus("error") is AgentStatus.error
        assert AgentStatus("offline") is AgentStatus.offline

    def test_enum_serialization(self):
        """Test that enum serializes to string, not integer."""
        assert str(AgentStatus.idle) == "idle"
        assert AgentStatus.idle.value == "idle"
        # Ensure it's not an integer enum
        assert not isinstance(AgentStatus.idle.value, int)

    def test_invalid_value_raises(self):
        """Test that invalid values raise ValueError."""
        with pytest.raises(ValueError):
            AgentStatus("invalid_status")


class TestTaskStatus:
    """Tests for TaskStatus enum."""

    def test_enum_values(self):
        """Test that all enum variants have correct string values."""
        assert TaskStatus.pending == "pending"
        assert TaskStatus.running == "running"
        assert TaskStatus.completed == "completed"
        assert TaskStatus.failed == "failed"
        assert TaskStatus.cancelled == "cancelled"

    def test_enum_membership(self):
        """Test that all variants are in the enum."""
        assert TaskStatus("pending") is TaskStatus.pending
        assert TaskStatus("running") is TaskStatus.running
        assert TaskStatus("completed") is TaskStatus.completed
        assert TaskStatus("failed") is TaskStatus.failed
        assert TaskStatus("cancelled") is TaskStatus.cancelled

    def test_enum_serialization(self):
        """Test that enum serializes to string, not integer."""
        assert str(TaskStatus.pending) == "pending"
        assert TaskStatus.pending.value == "pending"
        assert not isinstance(TaskStatus.pending.value, int)

    def test_invalid_value_raises(self):
        """Test that invalid values raise ValueError."""
        with pytest.raises(ValueError):
            TaskStatus("invalid_status")


class TestPriority:
    """Tests for Priority enum."""

    def test_enum_values(self):
        """Test that all enum variants have correct string values."""
        assert Priority.low == "low"
        assert Priority.normal == "normal"
        assert Priority.high == "high"
        assert Priority.critical == "critical"

    def test_enum_membership(self):
        """Test that all variants are in the enum."""
        assert Priority("low") is Priority.low
        assert Priority("normal") is Priority.normal
        assert Priority("high") is Priority.high
        assert Priority("critical") is Priority.critical

    def test_enum_serialization(self):
        """Test that enum serializes to string, not integer."""
        assert str(Priority.low) == "low"
        assert Priority.low.value == "low"
        assert not isinstance(Priority.low.value, int)

    def test_invalid_value_raises(self):
        """Test that invalid values raise ValueError."""
        with pytest.raises(ValueError):
            Priority("invalid_priority")


class TestDependencyType:
    """Tests for DependencyType enum."""

    def test_enum_values(self):
        """Test that all enum variants have correct string values."""
        assert DependencyType.sequential == "sequential"
        assert DependencyType.parallel == "parallel"
        assert DependencyType.conditional == "conditional"

    def test_enum_membership(self):
        """Test that all variants are in the enum."""
        assert DependencyType("sequential") is DependencyType.sequential
        assert DependencyType("parallel") is DependencyType.parallel
        assert DependencyType("conditional") is DependencyType.conditional

    def test_enum_serialization(self):
        """Test that enum serializes to string, not integer."""
        assert str(DependencyType.sequential) == "sequential"
        assert DependencyType.sequential.value == "sequential"
        assert not isinstance(DependencyType.sequential.value, int)

    def test_invalid_value_raises(self):
        """Test that invalid values raise ValueError."""
        with pytest.raises(ValueError):
            DependencyType("invalid_type")


class TestGenRandomUUID:
    """Tests for gen_random_uuid function."""

    def test_returns_uuid(self):
        """Test that gen_random_uuid returns a UUID object."""
        result = gen_random_uuid()
        assert isinstance(result, UUID)

    def test_returns_valid_uuid(self):
        """Test that gen_random_uuid returns a valid UUID v4."""
        result = gen_random_uuid()
        assert result.version == 4

    def test_unique_values(self):
        """Test that gen_random_uuid generates unique values."""
        uuids = [gen_random_uuid() for _ in range(100)]
        # All should be unique
        assert len(set(uuids)) == 100


class TestNowUTC:
    """Tests for now_utc function."""

    def test_returns_datetime(self):
        """Test that now_utc returns a datetime object."""
        result = now_utc()
        assert isinstance(result, datetime)

    def test_returns_timezone_aware(self):
        """Test that now_utc returns timezone-aware datetime."""
        result = now_utc()
        assert result.tzinfo is not None
        assert result.tzinfo == timezone.utc

    def test_returns_current_time(self):
        """Test that now_utc returns approximately current time."""
        before = datetime.now(timezone.utc)
        result = now_utc()
        after = datetime.now(timezone.utc)
        assert before <= result <= after


class TestBaseModelWithID:
    """Tests for BaseModelWithID."""

    def test_auto_generates_id(self):
        """Test that id is auto-generated on model creation."""
        model = BaseModelWithID()
        assert isinstance(model.id, UUID)
        assert model.id.version == 4

    def test_auto_generates_created_at(self):
        """Test that created_at is auto-generated on model creation."""
        model = BaseModelWithID()
        assert isinstance(model.created_at, datetime)
        assert model.created_at.tzinfo == timezone.utc

    def test_auto_generates_updated_at(self):
        """Test that updated_at is auto-generated on model creation."""
        model = BaseModelWithID()
        assert isinstance(model.updated_at, datetime)
        assert model.updated_at.tzinfo == timezone.utc

    def test_created_and_updated_same_on_creation(self):
        """Test that created_at and updated_at are equal on creation."""
        model = BaseModelWithID()
        # They should be very close (within a second)
        diff = abs((model.updated_at - model.created_at).total_seconds())
        assert diff < 1.0

    def test_touch_updates_timestamp(self):
        """Test that touch() method updates the updated_at field."""
        model = BaseModelWithID()
        original_updated = model.updated_at
        
        # Wait a tiny bit to ensure time difference
        import time
        time.sleep(0.01)
        
        model.touch()
        assert model.updated_at > original_updated

    def test_serialization_to_dict(self):
        """Test that model serializes to dict correctly."""
        model = BaseModelWithID()
        data = model.model_dump()
        
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data
        assert isinstance(data["id"], UUID)
        assert isinstance(data["created_at"], datetime)
        assert isinstance(data["updated_at"], datetime)

    def test_serialization_to_json(self):
        """Test that model serializes to JSON correctly."""
        model = BaseModelWithID()
        json_str = model.model_dump_json()
        data = json.loads(json_str)
        
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data
        # UUID should be serialized as string
        assert isinstance(data["id"], str)
        # DateTime should be serialized as ISO format string
        assert isinstance(data["created_at"], str)
        assert isinstance(data["updated_at"], str)

    def test_deserialization_from_dict(self):
        """Test that model can be created from dict."""
        test_data = {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "created_at": "2026-03-22T12:00:00Z",
            "updated_at": "2026-03-22T13:00:00Z"
        }
        model = BaseModelWithID(**test_data)
        
        assert model.id == UUID("550e8400-e29b-41d4-a716-446655440000")
        assert model.created_at.year == 2026
        assert model.created_at.month == 3
        assert model.created_at.day == 22

    def test_extra_fields_ignored(self):
        """Test that extra fields are ignored."""
        test_data = {
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "created_at": "2026-03-22T12:00:00Z",
            "updated_at": "2026-03-22T13:00:00Z",
            "extra_field": "should be ignored"
        }
        model = BaseModelWithID(**test_data)
        # Should not have extra_field attribute
        assert not hasattr(model, "extra_field")


class TestEnumWithPydantic:
    """Tests for enum usage with Pydantic models."""

    class EnumTestModel(BaseModel):
        """Test model using enums."""
        agent_status: AgentStatus
        task_status: TaskStatus
        priority: Priority
        dependency_type: DependencyType

    def test_enum_in_pydantic_model(self):
        """Test that enums work properly in Pydantic models."""
        model = self.EnumTestModel(
            agent_status=AgentStatus.idle,
            task_status=TaskStatus.pending,
            priority=Priority.normal,
            dependency_type=DependencyType.sequential
        )
        
        assert model.agent_status == AgentStatus.idle
        assert model.task_status == TaskStatus.pending
        assert model.priority == Priority.normal
        assert model.dependency_type == DependencyType.sequential

    def test_enum_string_serialization(self):
        """Test that enums serialize to strings in Pydantic models."""
        model = self.EnumTestModel(
            agent_status=AgentStatus.busy,
            task_status=TaskStatus.running,
            priority=Priority.high,
            dependency_type=DependencyType.parallel
        )
        
        data = model.model_dump()
        assert data["agent_status"] == "busy"
        assert data["task_status"] == "running"
        assert data["priority"] == "high"
        assert data["dependency_type"] == "parallel"

    def test_enum_json_serialization(self):
        """Test that enums serialize to strings in JSON."""
        model = self.EnumTestModel(
            agent_status=AgentStatus.error,
            task_status=TaskStatus.failed,
            priority=Priority.critical,
            dependency_type=DependencyType.conditional
        )
        
        json_str = model.model_dump_json()
        data = json.loads(json_str)
        
        assert data["agent_status"] == "error"
        assert data["task_status"] == "failed"
        assert data["priority"] == "critical"
        assert data["dependency_type"] == "conditional"

    def test_enum_from_string_deserialization(self):
        """Test that enums can be created from strings."""
        model = self.EnumTestModel(
            agent_status="idle",
            task_status="completed",
            priority="low",
            dependency_type="parallel"
        )
        
        assert model.agent_status == AgentStatus.idle
        assert model.task_status == TaskStatus.completed
        assert model.priority == Priority.low
        assert model.dependency_type == DependencyType.parallel

    def test_enum_invalid_value_deserialization(self):
        """Test that invalid enum values raise validation error."""
        with pytest.raises(ValueError):
            self.EnumTestModel(
                agent_status="invalid",
                task_status=TaskStatus.pending,
                priority=Priority.normal,
                dependency_type=DependencyType.sequential
            )
