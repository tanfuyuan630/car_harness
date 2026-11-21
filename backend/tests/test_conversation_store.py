"""对话持久化特性测试：多行解析、列表、摘要与末轮更新。"""
from __future__ import annotations

from app.services import conversation_store


def test_save_and_load_multiline_turn(isolated_data):
    """多行用户与助手消息按原样保留。"""
    conversation_store.save_turn(
        "u1", "t1",
        "我想买一辆 SUV\n预算 20 万以内",
        "推荐如下：\n- 车型 A\n- 车型 B",
    )
    turns = conversation_store.load_conversation("u1", "t1")
    assert len(turns) == 1
    assert turns[0]["user"] == "我想买一辆 SUV\n预算 20 万以内"
    assert turns[0]["assistant"] == "推荐如下：\n- 车型 A\n- 车型 B"


def test_load_missing_conversation_returns_empty(isolated_data):
    """不存在的会话返回空列表。"""
    assert conversation_store.load_conversation("u1", "missing") == []


def test_tool_call_line_ignored_in_message(isolated_data):
    """工具调用行不混入用户或助手消息。"""
    conversation_store.save_turn(
        "u1", "t1", "查一下车型", "已查询", tool_calls=[{"name": "search_cars"}]
    )
    text = (isolated_data / "conversations" / "u1" / "t1.md").read_text(encoding="utf-8")
    assert "**工具调用**: search_cars" in text
    turn = conversation_store.load_conversation("u1", "t1")[0]
    assert turn["user"] == "查一下车型"
    assert turn["assistant"] == "已查询"


def test_list_conversations_title_and_summary_excluded(isolated_data):
    """会话列表排除摘要文件，标题取首条用户消息。"""
    conversation_store.save_turn("u1", "t1", "第一条问题", "回答")
    conversation_store.save_summary("u1", "t1", "摘要内容")
    items = conversation_store.list_conversations("u1")
    assert [item["thread_id"] for item in items] == ["t1"]
    assert items[0]["title"] == "第一条问题"


def test_summary_roundtrip(isolated_data):
    """摘要按字符串原样读写并去除首尾空白。"""
    assert conversation_store.load_summary("u1", "t1") == ""
    conversation_store.save_summary("u1", "t1", "  用户预算 20 万  ")
    assert conversation_store.load_summary("u1", "t1") == "用户预算 20 万"


def test_update_last_assistant_only_last_turn(isolated_data):
    """只更新最后一轮助手消息，历史轮次保持不变。"""
    conversation_store.save_turn("u1", "t1", "问题一", "旧回答一")
    conversation_store.save_turn("u1", "t1", "问题二", "旧回答二")
    assert conversation_store.update_last_assistant("u1", "t1", "最终回答二") is True
    turns = conversation_store.load_conversation("u1", "t1")
    assert [t["assistant"] for t in turns] == ["旧回答一", "最终回答二"]


def test_update_last_assistant_missing_file(isolated_data):
    """会话文件不存在时返回 False。"""
    assert conversation_store.update_last_assistant("u1", "missing", "内容") is False
