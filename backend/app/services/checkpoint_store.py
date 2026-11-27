"""LangGraph Redis Checkpointer 的构建、初始化与释放。

使用官方 langgraph-checkpoint-redis，要求 Redis 8 或安装 RedisJSON/RediSearch。
降级开启时 Redis 不可用改用内存检查点启动；降级关闭时保持启动失败。
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from redis.backoff import ExponentialBackoff
from redis.retry import Retry

from app.agent.degrade import (
    DegradeComponent,
    degrade_enabled,
    force_degraded,
    log_degrade,
    mark_component_degraded,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

_saver: BaseCheckpointSaver | None = None
_context_manager: Any = None
_redis_client: Any = None


def build_connection_args() -> dict[str, Any]:
    """构造 Redis 客户端连接参数：超时与指数退避重试。"""
    return {
        "socket_timeout": settings.REDIS_SOCKET_TIMEOUT_SECONDS,
        "socket_connect_timeout": settings.REDIS_SOCKET_TIMEOUT_SECONDS,
        "retry": Retry(
            ExponentialBackoff(base=0.2, cap=2.0),
            settings.REDIS_RETRY_ATTEMPTS,
        ),
        "retry_on_timeout": True,
    }


def _ttl_config() -> dict[str, Any]:
    return {
        "default_ttl": max(1, settings.REDIS_CHECKPOINT_TTL_MINUTES),
        "refresh_on_read": True,
    }


def _memory_degraded(reason: str, address: str, error: str = "-") -> BaseCheckpointSaver:
    """切换到内存检查点并标记进程级降级，返回内存 Saver。"""
    mark_component_degraded(DegradeComponent.CHECKPOINT)
    log_degrade(DegradeComponent.CHECKPOINT, reason, address=address, error=error)
    logger.warning(
        "[Checkpointer] 已降级为内存检查点：检查点仅存于当前进程，重启即丢失；"
        "中断恢复与 TTL 维护不可用；不支持多 worker 部署"
    )
    return MemorySaver()


async def setup_checkpointer() -> BaseCheckpointSaver:
    """初始化 Checkpointer；降级开启时 Redis 失败改用内存检查点。"""
    global _saver, _context_manager, _redis_client

    if _saver is not None:
        return _saver

    if settings.CHECKPOINTER_TYPE == "memory":
        _saver = MemorySaver()
        logger.info("[Checkpointer] 使用内存模式（仅用于测试）")
        return _saver

    address = f"{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}"
    if force_degraded():
        _saver = _memory_degraded("forced", address)
        return _saver

    from langgraph.checkpoint.redis.aio import AsyncRedisSaver

    _context_manager = AsyncRedisSaver.from_conn_string(
        settings.redis_url,
        connection_args=build_connection_args(),
        ttl=_ttl_config(),
    )
    try:
        _saver = await _context_manager.__aenter__()
        await _saver.asetup()
    except Exception as exc:
        _saver = None
        if _context_manager is not None:
            try:
                await _context_manager.__aexit__(type(exc), exc, exc.__traceback__)
            except Exception:
                pass
            _context_manager = None
        if degrade_enabled():
            _saver = _memory_degraded("redis_unavailable", address, str(exc)[:200])
            return _saver
        raise RuntimeError(
            f"Redis Checkpointer 初始化失败（{address}）：{exc}。"
            "请确认 Redis 8.0 已启动，并已启用 RedisJSON 与 RediSearch（JSON.SET/FT.CREATE 可用）。"
        ) from exc

    _redis_client = getattr(_saver, "_redis", None)
    logger.info("[Checkpointer] Redis 初始化完成：%s", address)
    return _saver


async def close_checkpointer() -> None:
    """退出异步上下文并清空单例。"""
    global _saver, _context_manager, _redis_client

    if _context_manager is not None:
        try:
            await _context_manager.__aexit__(None, None, None)
        except Exception:
            logger.exception("[Checkpointer] 关闭 Redis 连接失败")
    _context_manager = None
    _redis_client = None
    _saver = None


def get_checkpointer() -> BaseCheckpointSaver:
    """返回已初始化的 Checkpointer；未初始化时抛出明确错误。"""
    if _saver is None:
        raise RuntimeError("Checkpointer 尚未初始化，请先调用 setup_checkpointer()")
    return _saver


def get_redis_client():
    """返回与 Checkpointer 共用的异步 Redis 客户端；内存模式返回 None。"""
    return _redis_client
