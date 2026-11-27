"""IM 消息处理管线: 身份映射 -> 中断处理/记忆上下文 -> Agent 流式调用 -> 持久化。"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import Command

from app.agent.degrade import reset_request_degrade
from app.agent.harness import get_agent
from app.agent.error_policy import reset_recovery_budget
from app.agent.tiering import (
    prepare_main_tier,
    reset_main_tier,
    set_thread_tier,
    tier_name,
)
from app.agent.tools.recommendation_tool import FINAL_RECOMMENDATION_TOOL
from app.agent.tools.user_input_tool import ASK_USER_FOR_INPUT_TOOL
from app.channels.base import DeltaCallback, IncomingMessage
from app.core.config import settings
from app.core.db import SessionLocal
from app.services import conversation_store, memory_manager, thread_registry
from app.services.interrupts import (
    KIND_INPUT_REQUIRED,
    build_resume_value,
    interrupt_kind,
    pending_actions,
)
from app.services.user_service import get_or_create_im_user

logger = logging.getLogger(__name__)

APPROVAL_TIP = "该推荐需人工确认，请回复「批准」或「拒绝」完成确认"
INPUT_TIP = "请直接回复需要补充的信息，或回复「拒绝」取消"
_APPROVE_WORDS = {"批准", "通过", "同意", "approve"}
_REJECT_WORDS = {"拒绝", "驳回", "取消", "reject"}


def _build_messages(user_id: str, thread_id: str, new_message: str) -> list[dict]:
    """根据摘要 + 滑动窗口构建 Agent 输入消息列表, 与 Web 端保持一致。"""
    ctx = memory_manager.build_context(user_id, thread_id)
    messages: list[dict] = []
    if ctx["summary"]:
        messages.append({"role": "system", "content": f"【历史摘要】\n{ctx['summary']}"})
    for turn in ctx["recent"]:
        if turn["user"]:
            messages.append({"role": "user", "content": turn["user"]})
        if turn["assistant"]:
            messages.append({"role": "assistant", "content": turn["assistant"]})
    messages.append({"role": "user", "content": new_message})
    return messages


def _extract_answer(result: dict[str, Any]) -> str:
    """提取回复文本; 最终推荐与补充信息追问都附加对应提示。"""
    msgs = result.get("messages", [])
    last = msgs[-1] if msgs else None
    if isinstance(last, AIMessage):
        for call in last.tool_calls or []:
            name = call.get("name")
            args = call.get("args", {}) or {}
            if name == FINAL_RECOMMENDATION_TOOL.name:
                recommendation = args.get("recommendation", "")
                return f"{recommendation}\n\n{APPROVAL_TIP}"
            if name == ASK_USER_FOR_INPUT_TOOL.name:
                question = args.get("question", "")
                return f"{question}\n\n{INPUT_TIP}"
    content = last.content if last else ""
    if isinstance(content, list):
        content = " ".join(
            str(c.get("text", "")) if isinstance(c, dict) else str(c) for c in content
        )
    return str(content).strip()


def _first_pending(state) -> list[dict[str, Any]]:
    """返回全部待处理中断动作；没有中断时返回空列表。"""
    return pending_actions(state)


def _approval_decision(text: str) -> str | None:
    """把审批文本映射为 approve/reject，非审批指令返回 None。"""
    normalized = text.strip().lower()
    if normalized in _APPROVE_WORDS:
        return "approve"
    if normalized in _REJECT_WORDS:
        return "reject"
    return None


async def _resume_pending(
    agent, config: dict, actions: list[dict[str, Any]], text: str, tier: str | None = None
) -> str:
    """根据中断类型恢复执行，并覆盖最后一条助手消息。"""
    user_id = config["metadata"]["user_id"]
    thread_id = config["metadata"]["thread_id"]

    needs_input = any(
        interrupt_kind({"action_requests": [action]}) == KIND_INPUT_REQUIRED for action in actions
    )
    if needs_input:
        if text.strip().lower() in _REJECT_WORDS:
            decision = "reject"
        elif text.strip():
            decision = "edit"
        else:
            return INPUT_TIP
    else:
        decision = _approval_decision(text)
        if decision is None:
            return APPROVAL_TIP

    resume_value = build_resume_value(actions, decision, text if decision == "edit" else None)
    result = await agent.ainvoke(Command(resume=resume_value), config=config)
    answer = _extract_answer(result)
    if answer:
        conversation_store.update_last_assistant(user_id, thread_id, answer)
    await thread_registry.track_thread(user_id, thread_id, tier=tier)
    return answer


async def _run(user_id: str, thread_id: str, message: IncomingMessage, on_delta: DeltaCallback) -> str:
    """流式调用 Agent；存在中断时先处理审批或补充信息。"""
    agent = get_agent()
    reset_request_degrade()
    config = {
        "configurable": {"thread_id": thread_id},
        "run_name": f"{message.channel}-chat",
        "tags": ["car-sales-agent", f"channel:{message.channel}", f"user:{user_id}"],
        "metadata": {
            "thread_id": thread_id,
            "user_id": user_id,
            "channel": message.channel,
        },
    }
    reset_recovery_budget()

    state = await agent.aget_state(config)
    actions = _first_pending(state)

    # 分档开启时：新消息入口分类，中断恢复复用线程最近档位
    tier: str | None = None
    if settings.LLM_TIER_ENABLED:
        if actions:
            meta = await thread_registry.get_thread_meta(thread_id)
            tier = tier_name(set_thread_tier(meta.get("tier"), thread_id, "im-resume"))
        else:
            previous = conversation_store.last_assistant_text(user_id, thread_id)
            tier = tier_name(await prepare_main_tier(message.text, previous, thread_id))
        config["metadata"]["llm_tier"] = tier
        config["tags"].append(f"tier:{tier}")
    await thread_registry.track_thread(user_id, thread_id, tier=tier)

    try:
        if actions:
            return await _resume_pending(agent, config, actions, message.text, tier)

        messages = _build_messages(user_id, thread_id, message.text)

        full_content = ""
        async for event in agent.astream_events({"messages": messages}, config=config, version="v2"):
            etype = event.get("event")
            data = event.get("data", {})
            meta = event.get("metadata") or {}
            # 只取主图模型流，过滤子智能体（子图）内部输出，与 Web 端口径一致
            ns = meta.get("checkpoint_ns", "") or ""
            if ns and not ns.startswith("model:"):
                continue
            if etype == "on_chat_model_stream":
                chunk = data.get("chunk")
                if chunk and hasattr(chunk, "content") and chunk.content:
                    text = chunk.content
                    if isinstance(text, list):
                        text = "".join(t.get("text", "") if isinstance(t, dict) else str(t) for t in text)
                    if text:
                        full_content += str(text)
                        on_delta(full_content)

        # 流结束后读取最终状态，统一处理最终推荐与补充信息场景
        state = await agent.aget_state(config)
        answer = _extract_answer(state.values) or full_content
        await memory_manager.update_memory(user_id, thread_id, message.text, answer)
        return answer
    finally:
        reset_main_tier()


def handle_im_message(message: IncomingMessage, on_delta: DeltaCallback) -> str:
    """IM 消息统一处理入口: 映射系统用户, 生成线程 ID, 流式调用 Agent 并返回回复。"""
    db = SessionLocal()
    try:
        user = get_or_create_im_user(db, message.channel, message.sender_id)
        user_id = user.user_id
    finally:
        db.close()

    thread_id = f"{message.channel}_{message.chat_id}_{message.sender_id}"
    try:
        return asyncio.run(_run(user_id, thread_id, message, on_delta))
    except Exception:
        logger.exception("[IM] 处理消息失败 thread=%s", thread_id)
        return "处理失败，请稍后重试"
