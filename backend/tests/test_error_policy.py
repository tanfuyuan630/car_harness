"""错误分级与重试策略测试。"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, RateLimitError

from app.agent.error_policy import (
    ErrorKind,
    FatalError,
    TransientExhausted,
    classify_exception,
    consume_recovery_budget,
    is_redis_unavailable,
    reset_recovery_budget,
    transient_retry,
)
from app.core.config import settings


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


def test_transient_errors_are_classified():
    """限流、超时、连接错误属于临时错误。"""
    assert classify_exception(_rate_limit_error()) == ErrorKind.TRANSIENT
    assert classify_exception(asyncio.TimeoutError()) == ErrorKind.TRANSIENT
    assert classify_exception(APITimeoutError(request=httpx.Request("POST", "https://x"))) == (
        ErrorKind.TRANSIENT
    )
    assert classify_exception(APIConnectionError(request=httpx.Request("POST", "https://x"))) == (
        ErrorKind.TRANSIENT
    )
    assert classify_exception(TransientExhausted("done")) == ErrorKind.TRANSIENT


def test_recoverable_errors_are_classified():
    """工具异常与 JSON 解析失败属于可恢复错误。"""
    from app.agent.error_policy import RecoverableToolError

    assert classify_exception(RecoverableToolError("bad tool")) == ErrorKind.RECOVERABLE
    assert classify_exception(json.JSONDecodeError("bad", "{", 0)) == ErrorKind.RECOVERABLE


def test_unknown_errors_are_fatal():
    """无法识别的异常按致命错误处理。"""
    assert classify_exception(ValueError("bug")) == ErrorKind.FATAL
    assert classify_exception(FatalError("fatal")) == ErrorKind.FATAL


def test_redis_unavailable_detection():
    """Redis 连接类错误单独识别，接口层据此返回 503。"""
    from redis.exceptions import ConnectionError as RedisConnectionError
    from redis.exceptions import TimeoutError as RedisTimeoutError

    assert is_redis_unavailable(RedisConnectionError("down")) is True
    assert is_redis_unavailable(RedisTimeoutError("timeout")) is True
    assert is_redis_unavailable(ValueError("other")) is False


def test_transient_retry_succeeds_after_rate_limit():
    """首次限流后自动重试并成功。"""
    calls = {"count": 0}

    async def flaky():
        calls["count"] += 1
        if calls["count"] == 1:
            raise _rate_limit_error()
        return "ok"

    async def run():
        reset_recovery_budget()
        return await transient_retry(flaky)()

    assert asyncio.run(run()) == "ok"
    assert calls["count"] == 2


def test_transient_retry_does_not_retry_fatal():
    """普通业务异常不重试。"""
    calls = {"count": 0}

    async def broken():
        calls["count"] += 1
        raise ValueError("bad request")

    async def run():
        return await transient_retry(broken)()

    with pytest.raises(ValueError):
        asyncio.run(run())
    assert calls["count"] == 1


def test_recovery_budget_escalates_to_fatal(monkeypatch):
    """可恢复错误超过上限后升级为致命错误。"""
    monkeypatch.setattr(settings, "MAX_RECOVERABLE_RETRIES", 2)
    reset_recovery_budget()
    consume_recovery_budget()
    consume_recovery_budget()
    with pytest.raises(FatalError):
        consume_recovery_budget()


def test_reset_recovery_budget(monkeypatch):
    """每轮请求重置预算后可重新累计。"""
    monkeypatch.setattr(settings, "MAX_RECOVERABLE_RETRIES", 1)
    reset_recovery_budget()
    consume_recovery_budget()
    reset_recovery_budget()
    consume_recovery_budget()
