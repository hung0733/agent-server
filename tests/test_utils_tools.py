import logging

import pytest

from backend.utils import Tools


@pytest.mark.asyncio
async def test_start_async_task_returns_async_result():
    async def job():
        return "done"

    task = Tools.start_async_task(job())

    assert await task == "done"


@pytest.mark.asyncio
async def test_start_async_task_propagates_exception():
    async def job():
        raise ValueError("failed")

    task = Tools.start_async_task(job())

    with pytest.raises(ValueError, match="failed"):
        await task


@pytest.mark.asyncio
async def test_start_async_task_logs_background_exception(caplog):
    async def job():
        raise ValueError("failed")

    caplog.set_level(logging.ERROR, logger="backend.utils.tools")
    task = Tools.start_async_task(job())

    with pytest.raises(ValueError, match="failed"):
        await task

    assert "背景 task 執行失敗" in caplog.text
