"""中断解析与恢复值构建。

deepagents 通过 HumanInTheLoopMiddleware 在 batched 模式下暂停：
中断值形如 {"action_requests": [{"name", "args", "description"}], "review_configs": [...]}，
恢复值必须是 {"decisions": [{"type": "approve" | "edit" | "reject" | "respond"}]}。
"""
from __future__ import annotations

from typing import Any

from app.agent.tools.user_input_tool import ASK_USER_FOR_INPUT_TOOL

KIND_RECOMMENDATION = "recommendation"
KIND_INPUT_REQUIRED = "input_required"


def _first_action(value: Any) -> dict[str, Any]:
    """取中断值里的第一个动作请求，没有则返回空字典。"""
    if isinstance(value, dict):
        requests = value.get("action_requests")
        if isinstance(requests, list) and requests and isinstance(requests[0], dict):
            return requests[0]
    return {}


def _action_args(action: dict[str, Any]) -> dict[str, Any]:
    args = action.get("args")
    return args if isinstance(args, dict) else {}


def interrupt_kind(value: Any) -> str:
    """按动作名称区分补充信息与最终推荐两类中断。"""
    if _first_action(value).get("name") == ASK_USER_FOR_INPUT_TOOL.name:
        return KIND_INPUT_REQUIRED
    return KIND_RECOMMENDATION


def interrupt_question(value: Any) -> str:
    """提取补充信息中断的追问文本。"""
    return str(_action_args(_first_action(value)).get("question") or "")


def interrupt_recommendation(value: Any) -> str:
    """提取最终推荐中断的推荐内容。"""
    return str(_action_args(_first_action(value)).get("recommendation") or "")


def pending_actions(state: Any) -> list[dict[str, Any]]:
    """从图状态中提取所有待处理的中断动作。"""
    actions: list[dict[str, Any]] = []
    for task in getattr(state, "tasks", []) or []:
        for interrupt in getattr(task, "interrupts", []) or []:
            action = _first_action(interrupt.value)
            if action:
                actions.append(action)
    return actions


def build_resume_value(
    actions: list[dict[str, Any]],
    decision: str,
    edited_content: str | None = None,
) -> dict[str, Any]:
    """把用户决定转换为 HumanInTheLoopMiddleware 需要的恢复值。

    - 补充信息中断：用户文本作为 respond 消息回填给模型；拒绝则回传 reject。
    - 最终推荐中断：approve / reject / edit，edit 保留原参数并覆盖推荐文本。
    """
    decisions: list[dict[str, Any]] = []
    text = (edited_content or "").strip()
    for action in actions:
        name = str(action.get("name") or "")
        args = _action_args(action)
        if name == ASK_USER_FOR_INPUT_TOOL.name:
            if decision == "reject":
                decisions.append({"type": "reject", "message": "用户取消了本次补充"})
            else:
                decisions.append({"type": "respond", "message": text})
        elif decision == "reject":
            decisions.append({"type": "reject", "message": "用户拒绝该推荐"})
        elif decision == "edit" and text:
            decisions.append(
                {
                    "type": "edit",
                    "edited_action": {
                        "name": name,
                        "args": {**args, "recommendation": text},
                    },
                }
            )
        else:
            decisions.append({"type": "approve"})
    return {"decisions": decisions}
