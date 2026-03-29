from __future__ import annotations

from pydantic import SecretStr

from models.llm import build_streaming_chat_openai


def test_build_streaming_chat_openai_enables_provider_usage():
    model = build_streaming_chat_openai(
        base_url="http://localhost:1234/v1",
        api_key=SecretStr("EMPTY"),
        model_name="qwen-test",
    )

    assert model.streaming is True
    assert model.stream_usage is True
    assert model.model_name == "qwen-test"
