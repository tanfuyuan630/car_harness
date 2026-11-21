"""ACP 文件生成工具：把生成文件的指令交给本地 TRAE CLI 执行。"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool

from app.core.config import settings
from app.services.acp_client import ACPClient, ACPError

ACP_FILE_TOOL_NAME = "generate_file_via_acp"


def _workspace() -> Path:
    return settings.workspace_dir_path.resolve()


def _resolve_target(filename: str) -> Path | None:
    """校验文件名为工作区内的相对路径，越界或含 .. 时返回 None。"""
    name = filename.strip()
    if not name:
        return None
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        return None
    target = (_workspace() / path).resolve()
    if not target.is_relative_to(_workspace()):
        return None
    return target


def _build_prompt(filename: str, target: Path, instruction: str) -> str:
    return (
        "请完成一个文件生成任务。\n"
        f"目标文件（相对工作区）：{filename}\n"
        f"目标文件绝对路径：{target}\n\n"
        f"内容要求：\n{instruction}\n\n"
        "要求：\n"
        "1. 只创建或覆盖目标文件，不要修改工作区中的其他文件。\n"
        "2. 内容使用中文，结构清晰，可直接交付给客户。\n"
        "3. 直接写入文件，完成后用一句话说明结果。"
    )


@tool
async def generate_file_via_acp(filename: str, instruction: str) -> str:
    """在工作区生成文本文件（方案、报告、清单、对比表等）。

    filename 为工作区相对路径（如 保险投保方案对比.md）；
    instruction 为文件的完整内容要求，需包含业务数据与结构说明。
    """
    target = _resolve_target(filename)
    if target is None:
        return "错误：filename 必须是工作区内的相对路径，且不能包含 .."

    prompt = _build_prompt(filename.strip(), target, instruction)
    client = ACPClient()
    try:
        await client.run_prompt(prompt)
    except ACPError as e:
        return f"错误：{e}"

    if not target.is_file():
        return f"错误：ACP 执行结束但未生成文件 {filename}"

    relative = target.relative_to(_workspace()).as_posix()
    return json.dumps(
        {
            "status": "ok",
            "path": relative,
            "name": target.name,
            "size": target.stat().st_size,
        },
        ensure_ascii=False,
    )


def get_acp_file_tools() -> list:
    return [generate_file_via_acp]
