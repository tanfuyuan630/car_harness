"""工具错误包装测试：异常转错误文本，连续错误升级为致命错误。"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.tools import tool

from app.agent.error_policy import FatalError, reset_recovery_budget
from app.agent.tools.recoverable import recoverable_tool
from app.core.config import settings


@tool
def broken_tool(city: str) -> str:
    """总是抛错的测试工具。"""
    raise ValueError(f"查询失败：{city}")


def test_tool_error_becomes_message():
    """工具异常转换为 [工具错误] 文本，而不是中断整个请求。"""
    wrapped = recoverable_tool(broken_tool)
    assert wrapped.name == broken_tool.name
    reset_recovery_budget()
    result = asyncio.run(wrapped.ainvoke({"city": "杭州"}))
    assert result.startswith("[工具错误]")
    assert "查询失败：杭州" in result


def test_repeated_tool_errors_become_fatal(monkeypatch):
    """连续可恢复错误超过上限后抛出 FatalError。"""
    monkeypatch.setattr(settings, "MAX_RECOVERABLE_RETRIES", 1)
    wrapped = recoverable_tool(broken_tool)
    reset_recovery_budget()
    asyncio.run(wrapped.ainvoke({"city": "杭州"}))
    with pytest.raises(FatalError):
        asyncio.run(wrapped.ainvoke({"city": "上海"}))
