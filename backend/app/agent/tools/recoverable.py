"""工具错误包装：可恢复错误写入 State 并回到 Agent，而不是直接中断请求。"""
from __future__ import annotations

import asyncio
import logging

from langchain_core.tools import BaseTool, StructuredTool

from app.agent.error_policy import (
    FatalError,
    consume_recovery_budget,
    transient_retry,
)

logger = logging.getLogger(__name__)


def recoverable_tool(tool: BaseTool) -> BaseTool:
    """把工具异常转换为错误文本，交给 Agent 重新生成或改用其他工具。

    工具层失败（含业务校验、外部调用、JSON 解析）按可恢复处理；
    连续失败超过上限时 consume_recovery_budget 会抛出 FatalError 冒泡给开发者。
    """
    async def _call(**kwargs):
        async def _invoke():
            return await tool.ainvoke(kwargs)

        try:
            return await transient_retry(_invoke)()
        except (FatalError, asyncio.CancelledError):
            raise
        except Exception as exc:
            consume_recovery_budget()
            logger.warning("[工具可恢复错误] %s: %s", tool.name, exc)
            return (
                f"[工具错误] {type(exc).__name__}: {exc}。"
                "请检查参数后重试，或改用其他工具；不要向用户暴露该内部错误。"
            )

    return StructuredTool.from_function(
        coroutine=_call,
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
    )
