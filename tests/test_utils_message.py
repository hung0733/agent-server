import json

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from backend.dto.agent_msg_hist import AgentMsgHistCreate
from backend.utils.message import MsgUtil


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
