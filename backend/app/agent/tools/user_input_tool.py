"""用户补充信息工具：关键参数缺失或指令模糊时触发中断，等待用户补充后恢复。"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def ask_user_for_input(question: str, missing_fields: list[str]) -> str:
    """向用户追问缺失的关键信息，或澄清存在多解的指令。

    在最终推荐、报价、到店导航等高成本动作前，若预算、用途、车型、城市等关键参数
    缺失或存在多解，必须调用本工具，不要自行假设。调用后会暂停执行，等待用户补充。
    """
    return question


ASK_USER_FOR_INPUT_TOOL = ask_user_for_input
