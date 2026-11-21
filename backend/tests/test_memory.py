"""对话记忆特性测试：滑动窗口与增量摘要。"""
from __future__ import annotations

import asyncio

from app.services import memory_manager


def test_build_context_returns_recent_three_turns(isolated_data):
    """窗口最多保留最近 3 轮，摘要单独返回。"""
    from app.services import conversation_store

    for i in range(1, 6):
        conversation_store.save_turn("u1", "t1", f"问题{i}", f"回答{i}")
    conversation_store.save_summary("u1", "t1", "已有摘要")

    context = memory_manager.build_context("u1", "t1")
    assert context["summary"] == "已有摘要"
    assert [turn["user"] for turn in context["recent"]] == ["问题3", "问题4", "问题5"]


def test_update_memory_summarizes_only_newly_overflowed_turn(isolated_data, monkeypatch):
    """摘要只接收本次滑出窗口的那一轮，并基于已有摘要增量更新。"""
    calls: list[tuple[str, list[str]]] = []

    async def fake_summarize(existing: str, overflow_turns: list[dict]) -> str:
        calls.append((existing, [turn["user"] for turn in overflow_turns]))
        return f"摘要{len(calls)}"

    monkeypatch.setattr(memory_manager, "_summarize", fake_summarize)

    # 前三轮不触发摘要
    for i in range(1, 4):
        context = asyncio.run(memory_manager.update_memory("u1", "t1", f"问题{i}", f"回答{i}"))
    assert calls == []
    assert len(context["recent"]) == 3

    # 第四轮滑出第 1 轮
    asyncio.run(memory_manager.update_memory("u1", "t1", "问题4", "回答4"))
    assert calls == [("", ["问题1"])]

    # 第五轮只滑出第 2 轮，并携带已有摘要
    context = asyncio.run(memory_manager.update_memory("u1", "t1", "问题5", "回答5"))
    assert calls[-1] == ("摘要1", ["问题2"])
    assert context["summary"] == "摘要2"
    assert [turn["user"] for turn in context["recent"]] == ["问题3", "问题4", "问题5"]
