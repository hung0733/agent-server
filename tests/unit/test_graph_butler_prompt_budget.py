from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from graph.butler import _build_messages_with_token_budget


class TestGraphButlerPromptBudget:
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
