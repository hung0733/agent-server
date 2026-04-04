from unittest.mock import AsyncMock

import main


class TestMainShutdown:
    async def test_waits_for_background_tasks(self, monkeypatch):
        wait_task_comp_mock = AsyncMock()
        monkeypatch.setattr(main.Tools, "wait_task_comp", wait_task_comp_mock)

        await main._wait_for_background_tasks()

        wait_task_comp_mock.assert_awaited_once()
