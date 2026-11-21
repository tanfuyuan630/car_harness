"""错误分级与重试策略。

四类错误：
- TRANSIENT：网络抖动、限流、超时，自动有限重试。
- RECOVERABLE：工具调用或解析失败，错误写入 State 后回到 Agent 重新生成。
- USER_FIXABLE：缺少关键参数或指令模糊，由 Agent 触发 interrupt 追问。
- FATAL：未知错误或底层依赖崩溃，冒泡并保留检查点供人工断点重跑。
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextvars import ContextVar
from enum import Enum
from typing import Any, Awaitable, Callable

from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from app.core.config import settings

logger = logging.getLogger(__name__)


class ErrorKind(str, Enum):
    TRANSIENT = "transient"
    RECOVERABLE = "recoverable"
    USER_FIXABLE = "user_fixable"
    FATAL = "fatal"


class TransientExhausted(RuntimeError):
    """临时错误重试耗尽。"""


class FatalError(RuntimeError):
    """致命错误，需要冒泡给开发者。"""


class RecoverableToolError(RuntimeError):
    """工具层的可恢复错误。"""


def classify_exception(exc: BaseException) -> ErrorKind:
    """按异常类型归类；无法识别的异常一律视为致命错误。"""
    from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
    from pydantic import ValidationError
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import TimeoutError as RedisTimeoutError

    if isinstance(exc, FatalError):
        return ErrorKind.FATAL
    if isinstance(exc, TransientExhausted):
        return ErrorKind.TRANSIENT
    if isinstance(
        exc,
        (
            RateLimitError,
            APITimeoutError,
            APIConnectionError,
            InternalServerError,
            RedisConnectionError,
            RedisTimeoutError,
            asyncio.TimeoutError,
            TimeoutError,
        ),
    ):
        return ErrorKind.TRANSIENT
    if isinstance(exc, (RecoverableToolError, json.JSONDecodeError, ValidationError)):
        return ErrorKind.RECOVERABLE
    return ErrorKind.FATAL


def is_redis_unavailable(exc: BaseException) -> bool:
    """判断是否为 Redis 连接类错误，用于返回 503 而非普通 502。"""
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import TimeoutError as RedisTimeoutError

    return isinstance(exc, (RedisConnectionError, RedisTimeoutError))


def transient_backoff(attempt: int) -> float:
    """第 attempt 次重试前的等待时间，带上限。"""
    return min(8.0, 0.5 * (2 ** max(0, attempt - 1)))


def max_llm_attempts() -> int:
    """模型调用的最大尝试次数，至少 1 次。"""
    return max(1, settings.LLM_MAX_RETRIES)


# 用可变容器承载计数：工具调用在独立任务上下文中执行，上下文复制共享同一列表
_recovery_attempts: ContextVar[list[int] | None] = ContextVar("recovery_attempts", default=None)


def reset_recovery_budget() -> None:
    """每轮请求开始时重置可恢复错误预算。"""
    _recovery_attempts.set([0])


def consume_recovery_budget() -> None:
    """消耗一次可恢复错误预算；超过上限升级为致命错误。"""
    budget = _recovery_attempts.get()
    if budget is None:
        budget = [0]
        _recovery_attempts.set(budget)
    budget[0] += 1
    if budget[0] > max(1, settings.MAX_RECOVERABLE_RETRIES):
        raise FatalError(
            f"可恢复错误连续出现 {budget[0]} 次，超过上限 {settings.MAX_RECOVERABLE_RETRIES}，转人工排查"
        )


def transient_retry(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """异步函数的临时错误重试装饰器（tenacity）。"""

    async def _wrapped(*args: Any, **kwargs: Any) -> Any:
        retryer = AsyncRetrying(
            retry=retry_if_exception(lambda exc: classify_exception(exc) == ErrorKind.TRANSIENT),
            stop=stop_after_attempt(max_llm_attempts()),
            wait=wait_exponential_jitter(initial=0.5, max=8),
            reraise=True,
        )
        return await retryer(func, *args, **kwargs)

    return _wrapped
