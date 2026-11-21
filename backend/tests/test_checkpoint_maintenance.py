"""检查点维护任务测试：未完成续期、超期清理。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services import checkpoint_maintenance, thread_registry
from app.services import checkpoint_maintenance as maintenance


class FakeAgent:
    """按线程返回不同状态的 Agent 替身。"""

    def __init__(self, states):
        self.states = states

    async def aget_state(self, config):
        return self.states[config["configurable"]["thread_id"]]


class FakeSaver:
    def __init__(self):
        self.deleted: list[str] = []

    async def adelete_thread(self, thread_id):
        self.deleted.append(thread_id)


def _state(*, interrupted: bool):
    tasks = [SimpleNamespace(interrupts=[object()])] if interrupted else []
    return SimpleNamespace(tasks=tasks)


def test_run_once_refreshes_pending_and_deletes_expired(monkeypatch):
    """待处理线程续期，已完成且元数据过期的线程被清理。"""
    agent = FakeAgent({"t1": _state(interrupted=True), "t2": _state(interrupted=False)})
    saver = FakeSaver()
    refreshed: list[str] = []
    untracked: list[str] = []

    async def list_threads():
        return ["t1", "t2"]

    async def get_thread_meta(thread_id):
        return {"last_active_at": "1"} if thread_id == "t2" else {"last_active_at": "9999999999"}

    async def refresh_thread(thread_id):
        refreshed.append(thread_id)

    async def untrack_thread(thread_id):
        untracked.append(thread_id)

    monkeypatch.setattr(maintenance, "get_checkpointer", lambda: saver)
    monkeypatch.setattr("app.agent.harness.get_agent", lambda: agent)
    monkeypatch.setattr(thread_registry, "list_threads", list_threads)
    monkeypatch.setattr(thread_registry, "get_thread_meta", get_thread_meta)
    monkeypatch.setattr(thread_registry, "refresh_thread", refresh_thread)
    monkeypatch.setattr(thread_registry, "untrack_thread", untrack_thread)

    asyncio.run(checkpoint_maintenance.run_once())

    assert refreshed == ["t1"]
    assert saver.deleted == ["t2"]
    assert untracked == ["t2"]
