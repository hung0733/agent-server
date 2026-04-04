from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage

from graph.butler import _build_messages_with_token_budget, _compact_react_state_if_needed


class TestGraphButlerPromptBudget:
    def test_compact_react_state_if_needed_summarizes_old_steps(self, monkeypatch):
        monkeypatch.setattr("graph.butler.Tools.get_token_count", lambda value: 80)

        existing_messages = [
            HumanMessage(content="user asks for city route", id="m1"),
            AIMessage(
                content="",
                tool_calls=[{"id": "tc1", "name": "find", "args": {"path": "src/app/api"}}],
                id="m2",
            ),
            ToolMessage(content="found route.ts", tool_call_id="call-1", name="find", id="m3"),
            AIMessage(content="checking route details", id="m4"),
        ]
        new_messages = [
            ToolMessage(content="route.ts contains GET handler", tool_call_id="call-2", name="read", id="m5")
        ]

        result = _compact_react_state_if_needed(
            summary="",
            existing_messages=existing_messages,
            new_messages=new_messages,
            max_tokens=250,
            keep_last_messages=2,
        )

        assert result is not None
        assert "user asks for city route" in result["summary"]
        assert "Tool call find" in result["summary"]
        assert result["messages"][0] == RemoveMessage(id="m1")
        assert result["messages"][1] == RemoveMessage(id="m2")
        assert result["messages"][2] == new_messages[0]

    def test_compact_react_state_if_needed_skips_when_within_budget(self, monkeypatch):
        monkeypatch.setattr("graph.butler.Tools.get_token_count", lambda value: 20)

        existing_messages = [HumanMessage(content="short", id="m1")]
        new_messages = [AIMessage(content="ok", id="m2")]

        result = _compact_react_state_if_needed(
            summary="",
            existing_messages=existing_messages,
            new_messages=new_messages,
            max_tokens=200,
            keep_last_messages=2,
        )

        assert result is None

    def test_build_messages_with_token_budget_logs_trim_summary(self, monkeypatch):
        def _fake_token_count(value):
            text = str(value)
            if text == "system":
                return 40
            if "summary" in text:
                return 20
            if text in {"m1", "m2", "m3"}:
                return 40
            if text == '{"level":':
                return 10
            return 0

        debug_calls = []

        monkeypatch.setattr("graph.butler.Tools.get_token_count", _fake_token_count)
        monkeypatch.setattr(
            "graph.butler.logger.debug",
            lambda message, *args: debug_calls.append((message, args)),
        )

        _build_messages_with_token_budget(
            sys_prompt="system",
            summary="summary",
            messages=[
                HumanMessage(content="m1"),
                AIMessage(content="m2"),
                HumanMessage(content="m3"),
            ],
            max_tokens=210,
            assistant_prefill=AIMessage(content='{"level":'),
            label="level_1",
        )

        assert len(debug_calls) == 1
        message, args = debug_calls[0]
        assert "Prompt budget" in str(message)
        assert args == (
            "level_1",
            210,
            260,
            204,
            3,
            2,
            1,
            True,
            False,
        )

    def test_build_messages_with_token_budget_keeps_newest_messages(self, monkeypatch):
        def _fake_token_count(value):
            text = str(value)
            if text == "system":
                return 40
            if "summary" in text:
                return 20
            if text in {"m1", "m2", "m3"}:
                return 40
            return 0

        monkeypatch.setattr("graph.butler.Tools.get_token_count", _fake_token_count)

        result = _build_messages_with_token_budget(
            sys_prompt="system",
            summary="summary",
            messages=[
                HumanMessage(content="m1"),
                AIMessage(content="m2"),
                HumanMessage(content="m3"),
            ],
            max_tokens=210,
        )

        assert [type(message) for message in result] == [
            SystemMessage,
            AIMessage,
            AIMessage,
            HumanMessage,
        ]
        assert result[0].content == "system"
        assert "summary" in str(result[1].content)
        assert [message.content for message in result[2:]] == ["m2", "m3"]

    def test_build_messages_with_token_budget_drops_oversized_summary(self, monkeypatch):
        def _fake_token_count(value):
            text = str(value)
            if text == "system":
                return 40
            if "summary" in text:
                return 300
            if text == "m1":
                return 40
            return 0

        monkeypatch.setattr("graph.butler.Tools.get_token_count", _fake_token_count)

        result = _build_messages_with_token_budget(
            sys_prompt="system",
            summary="summary",
            messages=[HumanMessage(content="m1")],
            max_tokens=140,
        )

        assert [type(message) for message in result] == [SystemMessage, HumanMessage]
        assert [message.content for message in result] == ["system", "m1"]
