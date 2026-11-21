"""中断解析与恢复值构建测试。"""
from __future__ import annotations

from types import SimpleNamespace

from app.services.interrupts import (
    KIND_INPUT_REQUIRED,
    KIND_RECOMMENDATION,
    build_resume_value,
    interrupt_kind,
    interrupt_question,
    interrupt_recommendation,
    pending_actions,
)


def _hitl(*actions) -> dict:
    return {"action_requests": list(actions), "review_configs": []}


def test_recommendation_interrupt():
    """最终推荐中断提取推荐文本。"""
    value = _hitl(
        {
            "name": "final_recommendation_tool",
            "args": {"recommendation": "推荐比亚迪宋 PLUS"},
            "description": "待确认",
        }
    )
    assert interrupt_kind(value) == KIND_RECOMMENDATION
    assert interrupt_recommendation(value) == "推荐比亚迪宋 PLUS"


def test_input_required_interrupt():
    """补充信息中断识别类型并提取追问文本。"""
    value = _hitl(
        {
            "name": "ask_user_for_input",
            "args": {"question": "您的预算区间是多少", "missing_fields": ["预算"]},
            "description": "需要补充信息",
        }
    )
    assert interrupt_kind(value) == KIND_INPUT_REQUIRED
    assert interrupt_question(value) == "您的预算区间是多少"


def test_pending_actions_from_state():
    """从图状态中收集全部中断动作。"""
    value = _hitl({"name": "ask_user_for_input", "args": {"question": "城市"}})
    state = SimpleNamespace(tasks=[SimpleNamespace(interrupts=[SimpleNamespace(value=value)])])
    actions = pending_actions(state)
    assert actions == [{"name": "ask_user_for_input", "args": {"question": "城市"}}]


def test_build_approve_and_reject():
    """批准与拒绝转换成 decisions。"""
    actions = [{"name": "final_recommendation_tool", "args": {"recommendation": "A"}}]
    assert build_resume_value(actions, "approve") == {"decisions": [{"type": "approve"}]}
    assert build_resume_value(actions, "reject")["decisions"][0]["type"] == "reject"


def test_build_edit_recommendation():
    """修改推荐时保留原参数并覆盖推荐内容。"""
    actions = [{"name": "final_recommendation_tool", "args": {"recommendation": "A"}}]
    value = build_resume_value(actions, "edit", "B")
    assert value == {
        "decisions": [
            {
                "type": "edit",
                "edited_action": {
                    "name": "final_recommendation_tool",
                    "args": {"recommendation": "B"},
                },
            }
        ]
    }


def test_build_respond_for_user_input():
    """补充信息以 respond 消息回填给模型。"""
    actions = [{"name": "ask_user_for_input", "args": {"question": "预算"}}]
    assert build_resume_value(actions, "edit", "20 万") == {
        "decisions": [{"type": "respond", "message": "20 万"}]
    }
    assert build_resume_value(actions, "reject")["decisions"][0]["type"] == "reject"
