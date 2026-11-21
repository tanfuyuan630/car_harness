"""IM 双类型中断处理测试：审批指令与补充信息文本。"""
from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage

from app.channels import handler


class FakeAgent:
    def __init__(self):
        self.resumes: list = []

    async def ainvoke(self, command, config=None):
        self.resumes.append(command.resume)
        return {"messages": [AIMessage(content="已处理")]}


CONFIG = {"configurable": {"thread_id": "im_t1"}, "metadata": {"user_id": "u1", "thread_id": "im_t1"}}

INPUT_ACTIONS = [{"name": "ask_user_for_input", "args": {"question": "预算多少"}}]
RECOMMENDATION_ACTIONS = [{"name": "final_recommendation_tool", "args": {"recommendation": "A"}}]


def _prepare(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        handler.conversation_store,
        "update_last_assistant",
        lambda user_id, thread_id, text: saved.update({"text": text}),
    )

    async def _track(user_id, thread_id, tier=None):
        return None

    monkeypatch.setattr(handler.thread_registry, "track_thread", _track)
    return saved


def test_user_input_resumes_with_text(monkeypatch):
    """补充信息文本以 respond 消息回填。"""
    saved = _prepare(monkeypatch)
    agent = FakeAgent()
    answer = asyncio.run(handler._resume_pending(agent, CONFIG, INPUT_ACTIONS, "预算 20 万"))
    assert agent.resumes == [{"decisions": [{"type": "respond", "message": "预算 20 万"}]}]
    assert answer == "已处理"
    assert saved["text"] == "已处理"


def test_user_input_can_be_cancelled(monkeypatch):
    """补充信息阶段回复拒绝表示取消。"""
    _prepare(monkeypatch)
    agent = FakeAgent()
    asyncio.run(handler._resume_pending(agent, CONFIG, INPUT_ACTIONS, "拒绝"))
    assert agent.resumes == [{"decisions": [{"type": "reject", "message": "用户取消了本次补充"}]}]


def test_recommendation_approve(monkeypatch):
    """审批词映射为 approve。"""
    _prepare(monkeypatch)
    agent = FakeAgent()
    asyncio.run(handler._resume_pending(agent, CONFIG, RECOMMENDATION_ACTIONS, "批准"))
    assert agent.resumes == [{"decisions": [{"type": "approve"}]}]


def test_recommendation_non_decision_returns_tip(monkeypatch):
    """非审批指令不恢复执行，直接提示。"""
    _prepare(monkeypatch)
    agent = FakeAgent()
    answer = asyncio.run(handler._resume_pending(agent, CONFIG, RECOMMENDATION_ACTIONS, "再说吧"))
    assert answer == handler.APPROVAL_TIP
    assert agent.resumes == []


def test_extract_answer_for_pending_tools():
    """中断后的中间回复能提取推荐与追问文本。"""
    recommendation = AIMessage(
        content="",
        tool_calls=[{"name": "final_recommendation_tool", "args": {"recommendation": "推荐 A"}, "id": "1"}],
    )
    assert handler._extract_answer({"messages": [recommendation]}) == f"推荐 A\n\n{handler.APPROVAL_TIP}"

    question = AIMessage(
        content="",
        tool_calls=[{"name": "ask_user_for_input", "args": {"question": "预算多少"}, "id": "2"}],
    )
    assert handler._extract_answer({"messages": [question]}) == f"预算多少\n\n{handler.INPUT_TIP}"
