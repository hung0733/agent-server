import json
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from openai.types.completion_usage import CompletionUsage

from backend.dto.agent_msg_hist import AgentMsgHistCreate
from backend.dto.llm_usage import LlmUsageCreate
from backend.utils.message import MsgUtil


class FakeUsageSession:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


class FakeUsageSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return None


def patch_llm_usage_save(monkeypatch):
    created = []
    session = FakeUsageSession()

    class FakeLlmUsageDAO:
        def __init__(self, dao_session):
            assert dao_session is session

        async def create(self, dto):
            created.append(dto)

    monkeypatch.setattr(
        "backend.utils.message.async_session_factory",
        lambda: FakeUsageSessionContext(session),
    )
    monkeypatch.setattr("backend.utils.message.LlmUsageDAO", FakeLlmUsageDAO)

    return created, session


def test_base_msg_to_msg_hist_rec_user():
    messages = [HumanMessage(content="你好")]
    result = MsgUtil.base_msg_to_msg_hist_rec(
        messages,
        session_db_id=1,
        step_id="step-1",
        conversation_metadata={"sender_name": "Alice", "recv_name": "Bot"},
    )

    assert len(result) == 1
    assert result[0].session_id == 1
    assert result[0].step_id == "step-1"
    assert result[0].sender == "Alice"
    assert result[0].msg_type == "user"
    assert result[0].content == "你好"
    assert result[0].meta_data is None


def test_base_msg_to_msg_hist_rec_assistant():
    messages = [AIMessage(content="Hello!")]
    result = MsgUtil.base_msg_to_msg_hist_rec(
        messages,
        session_db_id=1,
        step_id="step-1",
        conversation_metadata={"sender_name": "Alice", "recv_name": "Bot"},
    )

    assert len(result) == 1
    assert result[0].session_id == 1
    assert result[0].sender == "Bot"
    assert result[0].msg_type == "assistant"
    assert result[0].content == "Hello!"
    assert result[0].meta_data is None


def test_base_msg_to_msg_hist_rec_reasoning():
    messages = [
        AIMessage(
            content="Final answer",
            additional_kwargs={"reasoning_content": "Thinking step by step..."},
        )
    ]
    result = MsgUtil.base_msg_to_msg_hist_rec(
        messages,
        session_db_id=1,
        step_id="step-1",
        conversation_metadata={"sender_name": "Alice", "recv_name": "Bot"},
    )

    assert len(result) == 2
    assert result[0].msg_type == "reasoning"
    assert result[0].sender == "Bot"
    assert result[0].content == "Thinking step by step..."
    assert result[0].meta_data is None

    assert result[1].msg_type == "assistant"
    assert result[1].sender == "Bot"
    assert result[1].content == "Final answer"
    assert result[1].meta_data is None


def test_base_msg_to_msg_hist_rec_tool_call():
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search",
                    "args": {"query": "天氣"},
                    "id": "call-1",
                }
            ],
        )
    ]
    result = MsgUtil.base_msg_to_msg_hist_rec(
        messages,
        session_db_id=1,
        step_id="step-1",
        conversation_metadata={"sender_name": "Alice", "recv_name": "Bot"},
    )

    assert len(result) == 1
    assert result[0].msg_type == "tool_call"
    assert result[0].sender == "Bot"
    assert "search" in result[0].content
    assert "天氣" in result[0].content

    meta = json.loads(result[0].meta_data)
    assert meta["name"] == "search"
    assert meta["args"]["query"] == "天氣"
    assert meta["id"] == "call-1"


def test_base_msg_to_msg_hist_rec_tool_result():
    messages = [ToolMessage(content="查詢結果：晴天", tool_call_id="call-1")]
    result = MsgUtil.base_msg_to_msg_hist_rec(
        messages,
        session_db_id=1,
        step_id="step-1",
        conversation_metadata={"sender_name": "Alice", "recv_name": "Bot"},
    )

    assert len(result) == 1
    assert result[0].msg_type == "tool_result"
    assert result[0].sender == "system"
    assert result[0].content == "查詢結果：晴天"
    assert result[0].meta_data is None


def test_base_msg_to_msg_hist_rec_tool_call_args_truncation():
    long_arg = "a" * 200
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search",
                    "args": {"query": long_arg},
                    "id": "call-2",
                }
            ],
        )
    ]
    result = MsgUtil.base_msg_to_msg_hist_rec(
        messages,
        session_db_id=1,
        step_id="step-1",
        conversation_metadata={"sender_name": "Alice", "recv_name": "Bot"},
    )

    assert "..." in result[0].content
    assert len(result[0].content) < 200


def test_base_msg_to_msg_hist_rec_mixed_sequence():
    messages = [
        HumanMessage(content="Hi"),
        AIMessage(
            content="Let me check",
            additional_kwargs={"reasoning_content": "思考中..."},
            tool_calls=[
                {
                    "name": "search",
                    "args": {"query": "test"},
                    "id": "call-3",
                }
            ],
        ),
        ToolMessage(content="結果", tool_call_id="call-3"),
        AIMessage(content="完成"),
    ]

    metadata = {"sender_name": "Alice", "recv_name": "Bot"}
    result = MsgUtil.base_msg_to_msg_hist_rec(
        messages, session_db_id=42, step_id="step-2", conversation_metadata=metadata
    )

    assert len(result) == 6

    assert result[0].msg_type == "user"
    assert result[0].sender == "Alice"

    assert result[1].msg_type == "reasoning"
    assert result[1].sender == "Bot"
    assert result[1].session_id == 42
    assert result[1].step_id == "step-2"

    assert result[2].msg_type == "assistant"
    assert result[2].sender == "Bot"
    assert result[2].content == "Let me check"

    assert result[3].msg_type == "tool_call"
    assert result[3].sender == "Bot"

    assert result[4].msg_type == "tool_result"
    assert result[4].sender == "system"

    assert result[5].msg_type == "assistant"
    assert result[5].sender == "Bot"
    assert result[5].content == "完成"


def test_base_msg_to_tdai_memory_rec_allows_missing_datetime():
    messages = [
        HumanMessage(content="Hi"),
        AIMessage(
            content="Let me check",
            additional_kwargs={"datetime": datetime(2026, 5, 29, tzinfo=timezone.utc)},
            tool_calls=[
                {
                    "name": "search",
                    "args": {"query": "test"},
                    "id": "call-3",
                }
            ],
        ),
        ToolMessage(content="結果", tool_call_id="call-3"),
        AIMessage(content="完成"),
    ]

    user_msg, assistant_msg, cm, tcm = MsgUtil.base_msg_to_tdai_memory_rec(
        messages,
        conversation_metadata={"sender_name": "Alice", "recv_name": "Bot"},
    )

    assert user_msg == "Hi"
    assert assistant_msg == "Let me check\n\n完成\n\n"
    assert [msg.role for msg in cm] == ["user", "assistant", "assistant"]
    assert len(tcm) == 1
    assert tcm[0].tool_result == "結果"
    assert all(msg.timestamp > 0 for msg in cm)
    assert tcm[0].timestamp > 0


def test_base_msg_to_msg_hist_rec_empty_ai_content_no_records():
    messages = [AIMessage(content="")]
    result = MsgUtil.base_msg_to_msg_hist_rec(
        messages,
        session_db_id=1,
        step_id="step-1",
        conversation_metadata={"sender_name": "Alice", "recv_name": "Bot"},
    )
    assert len(result) == 0


def test_base_msg_to_msg_hist_rec_dto_type():
    messages = [HumanMessage(content="test")]
    result = MsgUtil.base_msg_to_msg_hist_rec(
        messages,
        session_db_id=1,
        step_id="step-1",
        conversation_metadata={"sender_name": "Alice", "recv_name": "Bot"},
    )
    assert isinstance(result[0], AgentMsgHistCreate)


def test_base_msg_to_msg_hist_rec_create_dt_from_message():
    from datetime import datetime, timezone

    dt = datetime(2026, 5, 28, 12, 0, 0, tzinfo=timezone.utc)
    messages = [
        HumanMessage(
            content="hi", additional_kwargs={"datetime": dt}
        )
    ]
    result = MsgUtil.base_msg_to_msg_hist_rec(
        messages,
        session_db_id=1,
        step_id="step-1",
        conversation_metadata={"sender_name": "Alice", "recv_name": "Bot"},
    )
    assert result[0].create_dt == dt


@pytest.mark.asyncio
async def test_save_llm_usage_uses_response_metadata_token_usage(monkeypatch):
    created, session = patch_llm_usage_save(monkeypatch)
    log_calls = []
    usage_dt = datetime(2026, 5, 28, 12, 30, 0, tzinfo=timezone.utc)
    response = AIMessage(
        content="hello",
        additional_kwargs={"datetime": usage_dt},
        response_metadata={
            "token_usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            }
        },
    )
    monkeypatch.setattr(
        "backend.utils.message.logger.info",
        lambda message, *args: log_calls.append((message, args)),
    )
    monkeypatch.setattr("backend.utils.message.t", lambda key: key)

    await MsgUtil.save_llm_usage(7, response)

    assert len(created) == 1
    assert isinstance(created[0], LlmUsageCreate)
    assert created[0].llm_endpoint_id == 7
    assert created[0].date_time == usage_dt
    assert created[0].in_token == 10
    assert created[0].out_token == 5
    assert created[0].cached_in_token == 0
    assert created[0].total_token == 15
    assert session.committed is True
    assert log_calls == [("utils.message.llm_usage_received", (15, 10, 5, 0))]


@pytest.mark.asyncio
async def test_save_llm_usage_prefers_usage_metadata(monkeypatch):
    created, session = patch_llm_usage_save(monkeypatch)
    response = AIMessage(
        content="hello",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            }
        },
        usage_metadata={
            "input_tokens": 12,
            "output_tokens": 6,
            "total_tokens": 18,
            "input_token_details": {"cache_read": 9},
        },
    )

    await MsgUtil.save_llm_usage(8, response)

    assert len(created) == 1
    assert created[0].llm_endpoint_id == 8
    assert created[0].in_token == 12
    assert created[0].cached_in_token == 9
    assert created[0].out_token == 6
    assert created[0].total_token == 18
    assert session.committed is True


@pytest.mark.asyncio
async def test_save_llm_usage_uses_prompt_cached_tokens(monkeypatch):
    created, session = patch_llm_usage_save(monkeypatch)
    response = AIMessage(
        content="hello",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18,
                "prompt_tokens_details": {"cached_tokens": 4},
            }
        },
    )

    await MsgUtil.save_llm_usage(10, response)

    assert len(created) == 1
    assert created[0].llm_endpoint_id == 10
    assert created[0].in_token == 11
    assert created[0].cached_in_token == 4
    assert created[0].out_token == 7
    assert created[0].total_token == 18
    assert session.committed is True


@pytest.mark.asyncio
async def test_save_llm_usage_accepts_token_usage_object(monkeypatch):
    created, session = patch_llm_usage_save(monkeypatch)
    response = AIMessage(
        content="hello",
        response_metadata={
            "token_usage": CompletionUsage(
                prompt_tokens=11,
                completion_tokens=7,
                total_tokens=18,
            )
        },
    )

    await MsgUtil.save_llm_usage(10, response)

    assert len(created) == 1
    assert created[0].llm_endpoint_id == 10
    assert created[0].in_token == 11
    assert created[0].cached_in_token == 0
    assert created[0].out_token == 7
    assert created[0].total_token == 18
    assert session.committed is True


@pytest.mark.asyncio
async def test_save_llm_usage_skips_missing_usage(monkeypatch):
    def fail_session_factory():
        raise AssertionError("session should not be opened")

    monkeypatch.setattr(
        "backend.utils.message.async_session_factory",
        fail_session_factory,
    )

    await MsgUtil.save_llm_usage(9, AIMessage(content="hello"))
