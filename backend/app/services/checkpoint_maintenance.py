"""检查点维护任务：未完成任务续期，已完成且超期的任务清理。"""
from __future__ import annotations

import asyncio
import logging
import time

from app.core.config import settings
from app.services import thread_registry
from app.services.checkpoint_store import get_checkpointer

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None


def _has_pending_interrupt(state) -> bool:
    return any(getattr(task, "interrupts", None) for task in getattr(state, "tasks", []) or [])


async def run_once() -> None:
    """执行一轮扫描：先续期待处理线程，再清理已完成且超期的线程。"""
    from app.agent.harness import get_agent

    agent = get_agent()
    saver = get_checkpointer()
    ttl_seconds = max(60, settings.REDIS_CHECKPOINT_TTL_MINUTES * 60)
    now = int(time.time())

    for thread_id in await thread_registry.list_threads():
        try:
            config = {"configurable": {"thread_id": thread_id}}
            # refresh_on_read=True：读取时自动续期检查点键
            state = await agent.aget_state(config)
            if _has_pending_interrupt(state):
                await thread_registry.refresh_thread(thread_id)
                continue

            meta = await thread_registry.get_thread_meta(thread_id)
            last_active = int(meta.get("last_active_at", "0") or 0)
            if not meta or now - last_active > ttl_seconds:
                await saver.adelete_thread(thread_id)
                await thread_registry.untrack_thread(thread_id)
                logger.info("[CheckpointMaintenance] 清理已完成线程：%s", thread_id)
        except Exception:
            logger.exception("[CheckpointMaintenance] 处理线程失败：%s", thread_id)


async def _loop() -> None:
    interval = max(60, settings.REDIS_MAINTENANCE_INTERVAL_SECONDS)
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[CheckpointMaintenance] 本轮扫描失败，等待下一轮")
        await asyncio.sleep(interval)


def start_maintenance() -> None:
    """启动后台维护任务。"""
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
        logger.info(
            "[CheckpointMaintenance] 已启动，间隔 %s 秒",
            settings.REDIS_MAINTENANCE_INTERVAL_SECONDS,
        )


async def stop_maintenance() -> None:
    """停止后台维护任务。"""
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
