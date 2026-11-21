"""最终推荐工具：Agent 在给出最终购车推荐前调用此工具，触发人机协同审批。"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def final_recommendation_tool(recommendation: str) -> str:
    """在向用户给出最终购车推荐结论之前，必须调用此工具以征求用户确认。
    传入你准备给出的推荐内容，等待用户批准后再输出。"""
    return f"待确认的推荐内容：{recommendation}\n请用户批准后再继续。"


FINAL_RECOMMENDATION_TOOL = final_recommendation_tool
