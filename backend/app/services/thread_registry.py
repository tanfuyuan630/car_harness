"""会话线程索引：记录活跃线程与最近活跃时间，供 TTL 续期和清理任务使用。"""
from __future__ import annotations

import time
from typing import Any

from app.core.config import settings
from app.services.checkpoint_store import get_redis_client

THREADS_SET_KEY = "lg:threads"
_META_PREFIX = "lg:thread_meta:"


def _ttl_seconds() -> int:
    return max(60, settings.REDIS_CHECKPOINT_TTL_MINUTES * 60)


def _meta_key(thread_id: str) -> str:
    return f"{_META_PREFIX}{thread_id}"


def _decode(value: Any) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


async def track_thread(user_id: str, thread_id: str, tier: str | None = None) -> None:
    """登记线程并刷新最近活跃时间；线程总集合不设过期，由清理任务维护。

    分档开启时传入 tier（low/medium/high），写入元数据供恢复与重试复用。
    """
    client = get_redis_client()
    if client is None:
        return
    key = _meta_key(thread_id)
    mapping = {"user_id": user_id, "last_active_at": int(time.time())}
    if tier is not None:
        mapping["tier"] = tier
    async with client.pipeline(transaction=False) as pipe:
        pipe.sadd(THREADS_SET_KEY, thread_id)
        pipe.hset(key, mapping=mapping)
        pipe.expire(key, _ttl_seconds())
        await pipe.execute()


async def refresh_thread(thread_id: str) -> None:
    """续期待处理线程的元数据。"""
    client = get_redis_client()
    if client is None:
        return
    key = _meta_key(thread_id)
    await client.hset(key, "last_active_at", int(time.time()))
    await client.expire(key, _ttl_seconds())


async def list_threads() -> list[str]:
    client = get_redis_client()
    if client is None:
        return []
    members = await client.smembers(THREADS_SET_KEY)
    return [_decode(item) for item in members]


async def get_thread_meta(thread_id: str) -> dict[str, str]:
    client = get_redis_client()
    if client is None:
        return {}
    raw = await client.hgetall(_meta_key(thread_id))
    return {_decode(k): _decode(v) for k, v in raw.items()}


async def untrack_thread(thread_id: str) -> None:
    client = get_redis_client()
    if client is None:
        return
    async with client.pipeline(transaction=False) as pipe:
        pipe.srem(THREADS_SET_KEY, thread_id)
        pipe.delete(_meta_key(thread_id))
        await pipe.execute()
