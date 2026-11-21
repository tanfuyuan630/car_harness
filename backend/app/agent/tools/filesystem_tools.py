"""虚拟文件系统工具：list_files / read_file / write_file，基于本地 workspace 目录。"""
from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool

from app.core.config import settings


def _workspace() -> Path:
    return settings.workspace_dir_path


@tool
def list_files_tool() -> str:
    """列出虚拟工作区中的所有文件。"""
    ws = _workspace()
    files = []
    for p in sorted(ws.rglob("*")):
        if p.is_file():
            rel = p.relative_to(ws)
            files.append({"path": str(rel), "size": p.stat().st_size})
    return json.dumps(files, ensure_ascii=False, indent=2)


@tool
def read_file_tool(filename: str) -> str:
    """读取虚拟工作区中指定文件的内容。传入文件名（相对路径）。"""
    ws = _workspace()
    target = (ws / filename).resolve()
    if not str(target).startswith(str(ws.resolve())):
        return "错误：禁止访问工作区外的文件"
    if not target.exists() or not target.is_file():
        return f"错误：文件 {filename} 不存在"
    return target.read_text(encoding="utf-8")


@tool
def write_file_tool(filename: str, content: str) -> str:
    """将内容写入虚拟工作区中的文件。传入文件名（相对路径）与内容字符串。"""
    ws = _workspace()
    target = (ws / filename).resolve()
    if not str(target).startswith(str(ws.resolve())):
        return "错误：禁止写入工作区外的文件"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"已写入文件 {filename}（{len(content)} 字符）"


FILESYSTEM_TOOLS = {
    "list_files": list_files_tool,
    "read_file": read_file_tool,
    "write_file": write_file_tool,
}


def get_filesystem_tools() -> list:
    return list(FILESYSTEM_TOOLS.values())
