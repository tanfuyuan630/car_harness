"""对话持久化服务：将用户对话以 Markdown 形式存储到本地文件。

存储结构：
    data/conversations/{user_id}/{thread_id}.md          真实对话记录（每轮追加）
    data/conversations/{user_id}/{thread_id}.summary.md   摘要（增量更新）
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from app.core.config import settings

TURN_HEADER_RE = re.compile(r"^##\s+\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", re.MULTILINE)


def _conv_dir(user_id: str) -> Path:
    """返回指定用户的对话目录，不存在则创建。"""
    d = settings.data_dir_path / "conversations" / user_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _conv_file(user_id: str, thread_id: str) -> Path:
    return _conv_dir(user_id) / f"{thread_id}.md"


def _summary_file(user_id: str, thread_id: str) -> Path:
    return _conv_dir(user_id) / f"{thread_id}.summary.md"


def save_turn(
    user_id: str,
    thread_id: str,
    user_msg: str,
    assistant_msg: str,
    tool_calls: list | None = None,
) -> None:
    """追加写入一轮对话到 Markdown 文件。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"\n## {ts}\n", f"**用户**: {user_msg}\n"]
    if tool_calls:
        names = ", ".join(tc.get("name", "") for tc in tool_calls if isinstance(tc, dict))
        if names:
            lines.append(f"**工具调用**: {names}\n")
    lines.append(f"**助手**: {assistant_msg}\n")
    with _conv_file(user_id, thread_id).open("a", encoding="utf-8") as f:
        f.write("".join(lines))


def load_conversation(user_id: str, thread_id: str) -> list[dict]:
    """读取某会话的全部历史轮次，返回 [{timestamp, user, assistant}]。

    支持多行消息：用户/助手消息可能包含换行，需要将后续非标记行
    追加到当前字段，直到遇到下一个标记或轮次结束。
    """
    f = _conv_file(user_id, thread_id)
    if not f.exists():
        return []
    text = f.read_text(encoding="utf-8")
    turns: list[dict] = []
    blocks = TURN_HEADER_RE.split(text)
    headers = TURN_HEADER_RE.findall(text)
    for header, block in zip(headers, blocks[1:]):
        ts = header.replace("## ", "").strip()
        user_msg = ""
        assistant_msg = ""
        current = None  # "user" / "assistant" / None
        for line in block.splitlines():
            if line.startswith("**用户**:"):
                user_msg = line.replace("**用户**:", "", 1).strip()
                current = "user"
            elif line.startswith("**助手**:"):
                assistant_msg = line.replace("**助手**:", "", 1).strip()
                current = "assistant"
            elif line.startswith("**工具调用**:"):
                current = None
            elif current == "user" and line.strip() != "":
                user_msg += "\n" + line
            elif current == "assistant" and line.strip() != "":
                assistant_msg += "\n" + line
        if user_msg or assistant_msg:
            turns.append({"timestamp": ts, "user": user_msg, "assistant": assistant_msg})
    return turns


def list_conversations(user_id: str) -> list[dict]:
    """列出该用户的所有会话，按修改时间倒序。"""
    d = _conv_dir(user_id)
    items: list[dict] = []
    for f in d.glob("*.md"):
        if f.name.endswith(".summary.md"):
            continue
        thread_id = f.stem
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        # 取第一条用户消息作为标题
        title = thread_id
        try:
            text = f.read_text(encoding="utf-8")
            for line in text.splitlines():
                if line.startswith("**用户**:"):
                    title = line.replace("**用户**:", "", 1).strip()[:50]
                    break
        except OSError:
            pass
        items.append({"thread_id": thread_id, "title": title, "updated_at": mtime})
    items.sort(key=lambda x: x["updated_at"], reverse=True)
    return items


def load_summary(user_id: str, thread_id: str) -> str:
    """读取摘要内容，不存在则返回空串。"""
    f = _summary_file(user_id, thread_id)
    if not f.exists():
        return ""
    return f.read_text(encoding="utf-8").strip()


def last_assistant_text(user_id: str, thread_id: str) -> str:
    """返回最近一轮的助手回复，用于复杂度分类参考上一条上下文。"""
    turns = load_conversation(user_id, thread_id)
    return turns[-1]["assistant"] if turns else ""


def save_summary(user_id: str, thread_id: str, summary: str) -> None:
    """覆盖写入摘要。"""
    _summary_file(user_id, thread_id).write_text(summary, encoding="utf-8")


def update_last_assistant(user_id: str, thread_id: str, assistant_msg: str) -> bool:
    """更新最后一轮的助手消息内容。用于中断恢复后补全最终回答。

    返回 True 表示更新成功，False 表示未找到可更新的轮次。
    """
    f = _conv_file(user_id, thread_id)
    if not f.exists():
        return False
    text = f.read_text(encoding="utf-8")
    # 找到最后一个 "**助手**:" 的位置，替换其后续内容直到下一个轮次标记或文件末尾
    idx = text.rfind("**助手**:")
    if idx == -1:
        return False
    # 从 "**助手**:" 之后开始，找到下一个轮次标记（## 开头的行）或文件末尾
    rest_start = idx + len("**助手**:")
    # 查找下一个轮次标题
    next_turn = TURN_HEADER_RE.search(text, rest_start)
    if next_turn:
        # 替换到下一轮次标题之前（保留换行与轮次标题）
        new_text = text[:rest_start] + " " + assistant_msg + "\n" + text[next_turn.start():]
    else:
        # 替换到文件末尾
        new_text = text[:rest_start] + " " + assistant_msg + "\n"
    f.write_text(new_text, encoding="utf-8")
    return True
