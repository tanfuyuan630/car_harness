"""对话记忆管理：摘要 + 滑动窗口（最近 3 轮）。

设计：
- 真实对话记录持久化在 {thread_id}.md（完整、追加）
- 摘要持久化在 {thread_id}.summary.md（增量更新）
- 滑动窗口不单独存储，每次从真实记录取末尾 WINDOW_SIZE 轮
"""
from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.llm import get_llm
from app.services import conversation_store

WINDOW_SIZE = 3

SUMMARY_PROMPT = (
    "你是一个对话摘要助手。请根据以下【已有摘要】和【新滑出窗口的对话】，"
    "生成一份更新后的简洁摘要，保留关键事实（用户偏好、预算、已提及车型、决策结论等），"
    "控制在 200 字以内，不要重复无关细节。\n\n"
    "【已有摘要】\n{existing}\n\n"
    "【新滑出的对话】\n{new_turns}\n\n"
    "请直接输出更新后的摘要。"
)


def build_context(user_id: str, thread_id: str) -> dict[str, Any]:
    """构建 Agent 输入上下文：摘要 + 最近 WINDOW_SIZE 轮。"""
    summary = conversation_store.load_summary(user_id, thread_id)
    turns = conversation_store.load_conversation(user_id, thread_id)
    recent = turns[-WINDOW_SIZE:] if len(turns) > WINDOW_SIZE else turns
    return {"summary": summary, "recent": recent}


def _format_turns(turns: list[dict]) -> str:
    parts = []
    for t in turns:
        parts.append(f"用户: {t['user']}\n助手: {t['assistant']}")
    return "\n\n".join(parts)


async def _summarize(existing: str, overflow_turns: list[dict]) -> str:
    """调用 LLM 生成增量摘要。"""
    prompt = SUMMARY_PROMPT.format(
        existing=existing or "（无）",
        new_turns=_format_turns(overflow_turns),
    )
    try:
        # 摘要属于内部工具调用，固定使用 OPENAI_MODEL，不参与分档
        resp = await get_llm().ainvoke(
            [SystemMessage(content=prompt)],
            config={
                "run_name": "memory-summary",
                "tags": ["car-sales-agent", "memory-summary"],
            },
        )
        text = resp.content if hasattr(resp, "content") else str(resp)
        if isinstance(text, list):
            text = "".join(t.get("text", "") if isinstance(t, dict) else str(t) for t in text)
        return str(text).strip()
    except Exception as e:
        # 摘要失败不阻塞对话，保留已有摘要并追加新轮次的原文兜底
        fallback = existing + "\n" + _format_turns(overflow_turns)
        return fallback[:1000]


async def update_memory(
    user_id: str, thread_id: str, user_msg: str, assistant_msg: str,
) -> dict[str, Any]:
    """保存本轮对话并更新摘要与窗口。"""
    # 1. 持久化真实记录
    conversation_store.save_turn(user_id, thread_id, user_msg, assistant_msg)

    # 2. 读取全部轮次，判断是否需要滑动摘要
    turns = conversation_store.load_conversation(user_id, thread_id)
    if len(turns) > WINDOW_SIZE:
        # 只取本次新滑出窗口的那一轮（索引 = 总轮数 - 窗口大小 - 1），
        # 避免将全部历史反复传入摘要，导致重复压缩且越来越长。
        newly_overflow_idx = len(turns) - WINDOW_SIZE - 1
        overflow = [turns[newly_overflow_idx]]
        existing = conversation_store.load_summary(user_id, thread_id)
        new_summary = await _summarize(existing, overflow)
        conversation_store.save_summary(user_id, thread_id, new_summary)

    # 3. 返回最新上下文供调用方使用
    return build_context(user_id, thread_id)
