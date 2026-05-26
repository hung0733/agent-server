from backend.tdai_memory.pipeline.l1_extraction import _EXTRACTION_PROMPT


def test_extraction_prompt_formats_with_json_example():
    prompt = _EXTRACTION_PROMPT.format(
        existing_memories_text="- [persona] 喜歡旅行",
        conversation_text="[user]: 我去過姬路城",
    )

    assert '"memories"' in prompt
    assert '"metadata": {}' in prompt
    assert "- [persona] 喜歡旅行" in prompt
    assert "[user]: 我去過姬路城" in prompt
