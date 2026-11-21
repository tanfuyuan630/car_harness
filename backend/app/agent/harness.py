"""Agent Harness 编排：使用 deepagents.create_deep_agent 组装所有注册组件。"""
from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent

from app.agent.registry import registry
from app.agent.tools.recommendation_tool import FINAL_RECOMMENDATION_TOOL
from app.agent.tools.user_input_tool import ASK_USER_FOR_INPUT_TOOL


def build_agent():
    """构建并返回编译后的 deep agent 图。"""
    tools = registry.tools + [FINAL_RECOMMENDATION_TOOL, ASK_USER_FOR_INPUT_TOOL]
    subagents = registry.subagents

    agent = create_deep_agent(
        model=registry.llm,
        tools=tools,
        system_prompt=registry.system_prompt,
        subagents=subagents,
        backend=registry.filesystem_backend,
        checkpointer=registry.checkpointer,
        # 人机协同：最终推荐审批与用户补充信息都触发中断
        interrupt_on={
            FINAL_RECOMMENDATION_TOOL.name: True,
            ASK_USER_FOR_INPUT_TOOL.name: True,
        },
    )
    return agent


# 全局单例（懒加载）
_agent = None


def get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


async def ainvoke_agent(message: str, thread_id: str) -> dict[str, Any]:
    """非流式调用 Agent。"""
    agent = get_agent()
    config = {
        "configurable": {"thread_id": thread_id},
        "run_name": "agent-invoke",
        "tags": ["car-sales-agent", "agent-invoke"],
        "metadata": {"thread_id": thread_id},
    }
    result = await agent.ainvoke({"messages": [{"role": "user", "content": message}]}, config=config)
    return result
