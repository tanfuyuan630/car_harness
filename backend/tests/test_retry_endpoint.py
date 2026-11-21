"""断点续跑接口测试：409 分支与从最后检查点继续。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from langchain_core.messages import AIMessage

from app import main as main_module


class FakeAgent:
    """最小可用的 Agent 替身，记录 ainvoke 的输入。"""

    def __init__(self, state, result=None):
        self.state = state
        self.result = result or {"messages": [AIMessage(content="已恢复")]}
        self.invoked: list = []

    async def aget_state(self, config):
        return self.state

    async def ainvoke(self, value, config=None):
        self.invoked.append(value)
        return self.result


def _state(*, interrupts=(), next_nodes=()):
    tasks = [SimpleNamespace(interrupts=list(interrupts))] if interrupts else []
    return SimpleNamespace(tasks=tasks, next=tuple(next_nodes))


def _user():
    return SimpleNamespace(user_id="u1")


def test_retry_rejects_pending_interrupt(monkeypatch):
    """待审批线程不允许直接重试。"""
    agent = FakeAgent(_state(interrupts=[object()]))
    monkeypatch.setattr(main_module, "get_agent", lambda: agent)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main_module.retry_thread("t1", _user()))
    assert exc.value.status_code == 409
    assert agent.invoked == []


def test_retry_rejects_no_pending_task(monkeypatch):
    """没有未完成节点时返回 409。"""
    agent = FakeAgent(_state())
    monkeypatch.setattr(main_module, "get_agent", lambda: agent)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main_module.retry_thread("t1", _user()))
    assert exc.value.status_code == 409
    assert agent.invoked == []


def test_retry_resumes_from_checkpoint(monkeypatch):
    """从最后成功检查点继续，不重复用户消息。"""
    agent = FakeAgent(_state(next_nodes=("model",)))
    saved = {}

    monkeypatch.setattr(main_module, "get_agent", lambda: agent)
    monkeypatch.setattr(
        main_module.conversation_store,
        "update_last_assistant",
        lambda user_id, thread_id, text: saved.update(
            {"user_id": user_id, "thread_id": thread_id, "text": text}
        ),
    )

    async def _track(user_id, thread_id, tier=None):
        return None

    monkeypatch.setattr(main_module.thread_registry, "track_thread", _track)

    result = asyncio.run(main_module.retry_thread("t1", _user()))
    assert agent.invoked == [None]
    assert result == {"thread_id": "t1", "content": "已恢复", "interrupted": False}
    assert saved == {"user_id": "u1", "thread_id": "t1", "text": "已恢复"}
