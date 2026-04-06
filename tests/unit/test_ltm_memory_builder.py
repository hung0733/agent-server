"""Tests for LTM memory builder parsing."""

from unittest.mock import MagicMock

import pytest

from ltm.core.memory_builder import MemoryBuilder


def _build_builder(extracted_json):
    llm_client = MagicMock()
    llm_client.extract_json.return_value = extracted_json
    return MemoryBuilder(llm_client=llm_client, vector_store=MagicMock())


def test_parse_llm_response_accepts_entries_object_wrapper():
    """Should accept JSON object wrappers produced by json_object mode."""
    builder = _build_builder(
        {
            "entries": [
                {
                    "lossless_restatement": "Alice scheduled a product review meeting.",
                    "keywords": ["Alice", "meeting"],
                    "timestamp": None,
                    "location": None,
                    "persons": ["Alice"],
                    "entities": [],
                    "topic": "Meeting scheduling",
                }
            ]
        }
    )

    entries = builder._parse_llm_response("{}", [1])

    assert len(entries) == 1
    assert entries[0].lossless_restatement == "Alice scheduled a product review meeting."


def test_parse_llm_response_rejects_non_list_payloads():
    """Should still reject object payloads that do not contain entry lists."""
    builder = _build_builder({"answer": "not a memory list"})

    with pytest.raises(ValueError, match="Expected JSON array"):
        builder._parse_llm_response("{}", [1])
